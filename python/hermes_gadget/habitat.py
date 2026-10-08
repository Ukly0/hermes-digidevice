"""Browser viewer for the native 466x466 round habitat firmware simulation."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from .habitat_assets import generate
from .sim import Simulator


NAMES = frozenset(("agumon", "gabumon", "biyomon", "tentomon", "palmon",
                   "gomamon", "patamon", "gatomon"))


def build_library(assets: Path) -> Path:
    root = Path(__file__).resolve().parents[2]
    build = root / "build" / "habitat"
    source = build / "habitat_assets.cpp"
    build.mkdir(parents=True, exist_ok=True)
    generate(assets, source)
    bundled_cmake = Path(sys.executable).parent / "cmake"
    cmake = str(bundled_cmake) if bundled_cmake.is_file() else "cmake"
    commands = (
        [cmake, "-S", str(root / "firmware"), "-B", str(build),
         f"-DHG_HABITAT_ASSETS_SOURCE={source}"],
        [cmake, "--build", str(build), "-j2"],
    )
    for command in commands:
        try:
            subprocess.run(command, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                f"Habitat build failed: {command!r}. Install CMake and a C++17 compiler, "
                "check the build output, or supply --library with a compatible native library."
            ) from exc
    for relative in ("libhgsim.so", "libhgsim.dylib", "hgsim.dll", "bin/hgsim.dll",
                     "Release/hgsim.dll", "bin/Release/hgsim.dll"):
        library = build / relative
        if library.is_file():
            return library
    raise RuntimeError(f"No native hgsim library found in {build}; check CMake output or use --library.")


def native_state(sim: Simulator) -> dict:
    for line in sim.console("habitat status").splitlines():
        if line.startswith("@habitat "):
            state = json.loads(line[len("@habitat "):])
            if isinstance(state, dict):
                return state
    raise RuntimeError("Native library lacks habitat status; rebuild the habitat-enabled firmware core.")


def framebuffer(sim: Simulator) -> Image.Image:
    return Image.frombytes("RGB", (466, 466), sim.rgb888())


def sync_clock(sim: Simulator, zone: ZoneInfo) -> None:
    epoch = int(time.time())
    offset = int(datetime.fromtimestamp(epoch, zone).utcoffset().total_seconds() // 60)
    result = sim.console("habitat clock " + json.dumps({"epoch": epoch, "offset": offset}))
    if not result.startswith("@ok"):
        raise RuntimeError("Native library lacks clock sync; rebuild the firmware core")


def deliver_event(sim: Simulator, event: dict) -> None:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    action = event.get("action")
    if action == "touch":
        if set(event) != {"action", "pressed", "x", "y"}:
            raise ValueError("invalid touch fields")
        if type(event["pressed"]) is not bool or any(
            type(event[key]) is not int or not 0 <= event[key] <= 465 for key in ("x", "y")
        ):
            raise ValueError("invalid touch sample")
        sim.touch(event["pressed"], event["x"], event["y"])
    elif action == "notify":
        if set(event) not in ({"action", "name"}, {"action", "name", "kind"}) or not isinstance(event.get("name"), str) or event["name"] not in NAMES:
            raise ValueError("unknown resident")
        kind = event.get("kind", "info")
        if not isinstance(kind, str) or kind not in {"info", "question", "error"}:
            raise ValueError("unknown notification kind")
        result = sim.console(f"habitat notify {event['name']} {kind}")
        if result.startswith("@error"):
            raise ValueError(result)
    elif action == "answer":
        if set(event) != {"action", "yes"} or type(event.get("yes")) is not bool:
            raise ValueError("answer must be an explicit boolean")
        result = sim.console("habitat yes" if event["yes"] else "habitat no")
        if result.startswith("@error"):
            raise ValueError(result)
    elif isinstance(action, str) and action in {"pause", "motion", "read", "back", "details"}:
        if set(event) != {"action"}:
            raise ValueError("unexpected event fields")
        result = sim.console(f"habitat {action}")
        if result.startswith("@error"):
            raise ValueError(result)
    else:
        raise ValueError("unknown action")
    sim.step()


def handler_for(sim: Simulator, allowed_origin: str | None):
    page = Path(__file__).with_name("habitat.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def reply(self, content: bytes, mime: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            if self.path == "/":
                self.reply(page, "text/html; charset=utf-8")
            elif self.path == "/frame.png":
                sim.step()
                out = BytesIO()
                framebuffer(sim).save(out, format="PNG")
                self.reply(out.getvalue(), "image/png")
            elif self.path == "/state":
                self.reply(json.dumps(native_state(sim)).encode(), "application/json")
            else:
                self.reply(b"Not found", "text/plain", 404)

        def do_POST(self) -> None:
            self.close_connection = True
            if self.path != "/event":
                self.reply(b"Not found", "text/plain", 404)
                return
            origin = self.headers.get("Origin")
            # Host must match the listening address, not an arbitrary reflected Host header.
            host, port = self.server.server_address[:2]
            authority = f"[{host}]" if ":" in host else host
            local_origins = {f"http://{authority}:{port}"}
            if host in ("127.0.0.1", "::1"):
                local_origins.add(f"http://localhost:{port}")
            if origin is not None and origin not in local_origins and origin != allowed_origin:
                self.reply(b"Forbidden", "text/plain", 403)
                return
            try:
                if self.headers.get("Transfer-Encoding") is not None:
                    raise ValueError("unsupported transfer encoding")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1:
                    raise ValueError("missing or duplicate length")
                length = int(lengths[0])
                if not 0 < length <= 1024:
                    raise ValueError("invalid event length")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("truncated event")
                deliver_event(sim, json.loads(body))
            except (ValueError, TypeError, KeyError, TimeoutError):
                self.reply(b"Invalid event", "text/plain", 400)
                return
            self.reply(json.dumps(native_state(sim)).encode(), "application/json")

        def log_message(self, fmt, *args) -> None:
            if self.path not in ("/frame.png", "/state"):
                super().log_message(fmt, *args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="external digimon-assets checkout")
    parser.add_argument("--library", type=Path, help="use an existing native library without generating/building assets")
    parser.add_argument("--host", default="127.0.0.1", help="explicit interface to bind (default: loopback only)")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--allowed-origin", help="exact trusted HTTPS reverse-proxy origin")
    parser.add_argument("--preview", type=Path, help="export native PNG or animated GIF without a browser")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--timezone", default="UTC", help="IANA timezone for the native home clock, e.g. Europe/Madrid")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 60:
        parser.error("--seconds must be finite, greater than 0 and at most 60")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.preview and args.preview.suffix.lower() not in (".png", ".gif"):
        parser.error("--preview must end in .png or .gif")
    if args.allowed_origin:
        try:
            origin = urlsplit(args.allowed_origin)
            valid = (origin.scheme == "https" and origin.hostname and origin.port != 0
                     and not origin.username and not origin.password and not origin.path
                     and not origin.query and not origin.fragment
                     and args.allowed_origin == f"https://{origin.netloc}")
        except ValueError:
            valid = False
        if not valid:
            parser.error("--allowed-origin must be an exact HTTPS origin without path or credentials")
    try:
        zone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        parser.error(f"Unknown timezone {args.timezone!r}: {exc}")
    sim = None
    try:
        library = args.library.expanduser().resolve() if args.library else build_library(args.assets.expanduser())
        sim = Simulator(library=library, board="sim-466x466-round", name="Net Ocean")
        sim.start(network=False)
        sim.console("habitat on")
        sync_clock(sim, zone)
        sim.step()
        native_state(sim)
        if args.preview:
            frames = []
            remaining = args.seconds
            while remaining > 1e-9:
                sim.run_for(min(0.1, remaining), interval=0.01)
                sim.step()
                remaining -= 0.1
                if args.preview.suffix.lower() == ".gif":
                    frames.append(framebuffer(sim))
            if frames:
                frames[0].save(args.preview, save_all=True, append_images=frames[1:], duration=100, loop=0)
            else:
                framebuffer(sim).save(args.preview)
            print(f"Preview: {args.preview}")
        else:
            with HTTPServer((args.host, args.port), handler_for(sim, args.allowed_origin)) as server:
                print(f"Habitat viewer: http://{args.host}:{server.server_port}/ (Ctrl+C to stop)", flush=True)
                # Tick even without browser polling, on the same thread as all
                # native input: App is deliberately not thread-safe.
                server.timeout = 0.01
                next_sync = time.monotonic() + 30
                while True:
                    sim.step()
                    if time.monotonic() >= next_sync:
                        sync_clock(sim, zone)
                        next_sync = time.monotonic() + 30
                    server.handle_request()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.error(str(exc))
    finally:
        if sim is not None:
            sim.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
