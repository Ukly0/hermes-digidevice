"""Native habitat integration; placeholder artwork needs no external assets.

Set HERMES_HABITAT_LIBRARY to test another built library. Without it, native
tests skip only when the default build/host library is absent.
"""

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

pytest.importorskip("PIL")
from PIL import Image

from hermes_gadget.habitat import deliver_event, framebuffer, handler_for, main, native_state
from hermes_gadget.habitat import sync_clock
from zoneinfo import ZoneInfo
from hermes_gadget.sim import Simulator
from hermes_gadget.sim.native import NativeDevice


@pytest.fixture
def library():
    explicit = os.environ.get("HERMES_HABITAT_LIBRARY")
    if explicit:
        path = Path(explicit).resolve()
        assert path.is_file(), f"HERMES_HABITAT_LIBRARY does not exist: {path}"
        return path
    build = Path(__file__).resolve().parents[1] / "build" / "host"
    for name in ("libhgsim.so", "libhgsim.dylib", "hgsim.dll", "bin/hgsim.dll", "Release/hgsim.dll"):
        path = build / name
        if path.is_file():
            return path
    pytest.skip("Build the native simulator or set HERMES_HABITAT_LIBRARY")


@pytest.fixture
def sim(library):
    instance = Simulator(library=library, board="sim-466x466-round", name="Net Ocean")
    try:
        instance.start(network=False)
        instance.console("habitat on")
        instance.step()
        native_state(instance)  # An old library is a failure, not a skipped integration test.
        yield instance
    finally:
        instance.close()


def test_native_device_and_round_framebuffer(sim):
    assert isinstance(sim.device, NativeDevice)
    assert sim.network_up is False
    image = framebuffer(sim)
    assert image.size == (466, 466)
    for point in ((0, 0), (465, 0), (0, 465), (465, 465)):
        assert image.getpixel(point) == (0, 0, 0)
    assert image.getbbox() is not None
    state = native_state(sim)
    assert len(state["residents"]) == 8
    assert state["selected"] == -1
    assert type(state["assets"]) is bool
    assert all(r["mode"] in {"walk", "rest", "pending"} for r in state["residents"])


def test_native_motion_and_toggles(sim):
    before = native_state(sim)
    pixels = sim.rgb888()
    sim.run_for(3)
    after = native_state(sim)
    assert after["frame"] > before["frame"]
    assert [(r["x"], r["y"]) for r in after["residents"]] != [
        (r["x"], r["y"]) for r in before["residents"]
    ]
    assert sim.rgb888() != pixels
    deliver_event(sim, {"action": "pause"})
    assert native_state(sim)["paused"] is True
    positions = [(r["x"], r["y"]) for r in native_state(sim)["residents"]]
    sim.run_for(0.3)
    assert [(r["x"], r["y"]) for r in native_state(sim)["residents"]] == positions
    deliver_event(sim, {"action": "motion"})
    assert native_state(sim)["reduced_motion"] is True
    deliver_event(sim, {"action": "pause"})
    assert native_state(sim)["paused"] is False


def test_notice_survives_native_touch_and_back_until_selected_read(sim):
    deliver_event(sim, {"action": "notify", "name": "palmon"})
    deliver_event(sim, {"action": "notify", "name": "gabumon"})
    before = native_state(sim)
    target = next(r for r in before["residents"] if r["name"] == "palmon")
    sim.run_for(0.3)
    state = native_state(sim)
    resident = next(r for r in state["residents"] if r["name"] == "palmon")
    assert resident["pending"] == 1
    assert resident["mode"] == "pending"
    assert (resident["x"], resident["y"]) == (target["x"], target["y"])
    x, y = round(resident["x"]), round(resident["y"])
    assert 0 <= x <= 465 and 0 <= y <= 465
    sim.touch(True, x, y)
    sim.step()
    sim.touch(False, x, y)
    sim.step()
    state = native_state(sim)
    assert state["residents"][state["selected"]]["name"] == "palmon"
    assert state["residents"][state["selected"]]["pending"] == 1
    deliver_event(sim, {"action": "back"})
    assert native_state(sim)["selected"] == -1
    deliver_event(sim, {"action": "read"})
    assert next(r for r in native_state(sim)["residents"] if r["name"] == "palmon")["pending"] == 1
    sim.touch(True, x, y)
    sim.step()
    sim.touch(False, x, y)
    sim.step()
    deliver_event(sim, {"action": "read"})
    state = native_state(sim)
    assert next(r for r in state["residents"] if r["name"] == "palmon")["pending"] == 0
    assert next(r for r in state["residents"] if r["name"] == "gabumon")["pending"] == 1


def test_native_automatic_demo_notice(sim):
    assert sum(r["pending"] for r in native_state(sim)["residents"]) == 0
    sim.run_for(6.2)
    assert sum(r["pending"] for r in native_state(sim)["residents"]) == 1


def test_host_supplies_real_zoned_time_to_native_renderer(sim, monkeypatch):
    monkeypatch.setattr("hermes_gadget.habitat.time.time", lambda: 1791496799)
    sync_clock(sim, ZoneInfo("Europe/Madrid"))
    state = native_state(sim)
    assert state["clock_known"] is True
    assert state["time"] == "23:59" and state["date"] == "JUE 08 OCT"
    # Fake Wi-Fi is down; the dot must not claim Hermes is online because the viewer is.
    assert state["link_online"] is False


def test_timezone_cli_rejects_invalid_zone_before_building():
    with pytest.raises(SystemExit):
        main(["--assets", "unused", "--timezone", "Unknown/Place"])


def test_timezone_data_available_without_system_database():
    result = subprocess.run(
        [sys.executable, "-c", "from zoneinfo import ZoneInfo; ZoneInfo('UTC'); ZoneInfo('Europe/Madrid')"],
        env={**os.environ, "PYTHONTZPATH": ""}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_typed_question_needs_consent_and_preserves_queued_information(sim):
    deliver_event(sim, {"action": "notify", "name": "biyomon", "kind": "question"})
    deliver_event(sim, {"action": "notify", "name": "biyomon", "kind": "info"})
    bird = native_state(sim)["residents"][2]
    assert bird["pending"] == 2 and bird["kind"] == "question" and bird["fresh"] is True
    for pressed in (True, False):
        deliver_event(sim, {"action": "touch", "pressed": pressed, "x": bird["cue_x"], "y": bird["cue_y"]})
    assert native_state(sim)["selected"] == 2
    with pytest.raises(ValueError):
        deliver_event(sim, {"action": "read"})
    with pytest.raises(ValueError):
        deliver_event(sim, {"action": "answer", "yes": True})
    deliver_event(sim, {"action": "details"})
    assert native_state(sim)["details"] is True
    sim.run_for(0.4)
    assert native_state(sim)["question_ready"] is True
    deliver_event(sim, {"action": "answer", "yes": False})
    bird = native_state(sim)["residents"][2]
    assert bird["pending"] == 1 and bird["kind"] == "info"
    assert bird["last_action"] == "no" and bird["last_id"] != 0
    assert native_state(sim)["details"] is False
    deliver_event(sim, {"action": "read"})
    assert native_state(sim)["residents"][2]["pending"] == 0


def test_new_marker_expires_without_dismissing_incident(sim):
    deliver_event(sim, {"action": "notify", "name": "tentomon", "kind": "error"})
    assert native_state(sim)["residents"][3]["fresh"] is True
    sim.run_for(3.1)
    developer = native_state(sim)["residents"][3]
    assert developer["fresh"] is False
    assert developer["pending"] == 1 and developer["kind"] == "error"
    for pressed in (True, False):
        deliver_event(sim, {"action": "touch", "pressed": pressed, "x": developer["cue_x"], "y": developer["cue_y"]})
    assert native_state(sim)["selected"] == 3
    deliver_event(sim, {"action": "read"})
    assert native_state(sim)["residents"][3]["last_action"] == "read"


def test_overflow_does_not_overwrite_an_unanswered_request(sim):
    deliver_event(sim, {"action": "notify", "name": "gatomon", "kind": "question"})
    original = native_state(sim)["residents"][7]["notice_id"]
    for _ in range(7):
        deliver_event(sim, {"action": "notify", "name": "gatomon", "kind": "info"})
    with pytest.raises(ValueError):
        deliver_event(sim, {"action": "notify", "name": "gatomon", "kind": "error"})
    cat = native_state(sim)["residents"][7]
    assert cat["pending"] == 8 and cat["notice_id"] == original and cat["kind"] == "question"


@pytest.mark.parametrize("seconds", ["inf", "nan", "0", "-1", "60.1"])
def test_cli_rejects_unbounded_duration(seconds):
    with pytest.raises(SystemExit) as exc:
        main(["--assets", "unused", "--seconds", seconds])
    assert exc.value.code == 2


@pytest.mark.parametrize("origin", ["http://trusted.test", "https://trusted.test/", "https://u:p@trusted.test", "https://trusted.test?q=1"])
def test_cli_requires_exact_https_origin(origin):
    with pytest.raises(SystemExit) as exc:
        main(["--assets", "unused", "--allowed-origin", origin])
    assert exc.value.code == 2


@pytest.mark.parametrize("event", [
    [], {}, {"action": []}, {"action": "select", "name": "palmon"},
    {"action": "notify", "name": "palmon\nhabitat off"},
    {"action": "notify", "name": []}, {"action": "back", "console": "help"},
    {"action": "notify", "name": "palmon", "kind": []},
    {"action": "notify", "name": "palmon", "kind": "question\nhabitat off"},
    {"action": "answer", "yes": "yes"}, {"action": "answer", "yes": 1},
    {"action": "answer", "yes": True, "console": "help"},
    {"action": "touch", "pressed": True, "x": -1, "y": 100},
    {"action": "touch", "pressed": True, "x": 466, "y": 100},
    {"action": "touch", "pressed": True, "x": float("nan"), "y": 100},
    {"action": "touch", "pressed": True, "x": True, "y": 100},
    {"action": "touch", "pressed": 1, "x": 100, "y": 100},
])
def test_invalid_input_never_reaches_simulator(event):
    with pytest.raises(ValueError):
        deliver_event(None, event)


@pytest.mark.parametrize("body,headers,expected", [
    (b'{}', {"Origin": "https://untrusted.test"}, 403),
    (b'{}', {"Origin": "http://evil.test", "Host": "evil.test"}, 403),
    (b'{}', {"Origin": "https://trusted.test"}, 400),
    (b'[]', {}, 400), (b'{', {}, 400), (b'\xff', {}, 400),
    (b'x' * 1025, {}, 400),
    (b'{"action":"touch","pressed":true,"x":466,"y":1}', {}, 400),
])
def test_http_rejects_untrusted_input_without_native_calls(body, headers, expected):
    # None deliberately fails if rejected input ever tries to call the core.
    with HTTPServer(("127.0.0.1", 0), handler_for(None, "https://trusted.test")) as server:
        server.timeout = 5
        url = f"http://127.0.0.1:{server.server_port}/event"

        def request():
            try:
                with urlopen(Request(url, data=body, headers=headers), timeout=5) as response:
                    return response.status
            except HTTPError as exc:
                exc.close()
                return exc.code

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(request)
            server.handle_request()
            assert result.result(timeout=5) == expected


@pytest.mark.parametrize("suffix", ["png", "gif"])
def test_preview_uses_native_library_without_assets(library, tmp_path, suffix, monkeypatch):
    def forbidden(*args):
        pytest.fail("--library must not generate assets or build")
    monkeypatch.setattr("hermes_gadget.habitat.build_library", forbidden)
    target = tmp_path / f"preview.{suffix}"
    assert main(["--assets", str(tmp_path / "absent"), "--library", str(library),
                 "--preview", str(target), "--seconds", "1"]) == 0
    with Image.open(target) as image:
        assert image.size == (466, 466)
        assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 0)
        if suffix == "gif":
            assert image.n_frames > 1


def test_startup_error_closes_simulator(monkeypatch):
    closed = []

    class BrokenSimulator:
        def __init__(self, **kwargs):
            assert kwargs["board"] == "sim-466x466-round"

        def start(self, network):
            assert network is False
            raise RuntimeError("startup failure")

        def close(self):
            closed.append(True)

    monkeypatch.setattr("hermes_gadget.habitat.Simulator", BrokenSimulator)
    with pytest.raises(SystemExit):
        main(["--assets", "unused", "--library", "unused.so"])
    assert closed == [True]


def test_server_origins_routes_and_malformed_events(library, tmp_path):
    origin = "https://demo.example.test:8443"
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "hermes_gadget.habitat", "--assets", str(tmp_path / "absent"),
         "--library", str(library), "--port", "0", "--allowed-origin", origin],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Read startup asynchronously so a native startup failure cannot hang this test.
        import queue
        import threading
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        line = lines.get(timeout=15)
        assert "Habitat viewer:" in line, line
        url = line.split()[2].rstrip("/")
        with urlopen(url + "/state", timeout=5) as response:
            before = json.load(response)["frame"]
        time.sleep(0.35)
        # Native ticks continue without any framebuffer request from a browser.
        with urlopen(url + "/state", timeout=5) as response:
            assert json.load(response)["frame"] > before
        with urlopen(url + "/frame.png", timeout=5) as response:
            with Image.open(BytesIO(response.read())) as image:
                assert image.size == (466, 466)
        request = Request(url + "/event", data=b'{"action":"notify","name":"palmon"}',
                          headers={"Origin": origin, "Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            state = json.load(response)
        assert next(r for r in state["residents"] if r["name"] == "palmon")["pending"] == 1
        for body, headers, code in (
            (b'{"action":"pause"}', {"Origin": "https://untrusted.example.test"}, 403),
            (b'{"action":"pause"}', {"Origin": "http://evil.test", "Host": "evil.test"}, 403),
            (b"[]", {}, 400), (b"{", {}, 400), (b"x" * 1025, {}, 400),
            (b'{"action":"touch","pressed":true,"x":466,"y":1}', {}, 400),
            (b'{"action":"console","line":"help"}', {}, 400),
        ):
            with pytest.raises(HTTPError) as exc:
                urlopen(Request(url + "/event", data=body, headers=headers), timeout=5)
            assert exc.value.code == code
        for path in ("/habitat.html", "/../pyproject.toml", "/console"):
            with pytest.raises(HTTPError) as exc:
                urlopen(url + path, timeout=5)
            assert exc.value.code == 404
    finally:
        process.terminate()
        process.communicate(timeout=5)
