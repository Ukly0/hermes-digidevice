"""Export registered PNG portraits to reusable static C++ and binary tiles.

Run: python -m hermes_gadget.portrait_assets --profile profile.json
     --assets /path/to/artwork --out /path/to/new-output-directory

Schema version 1 requires profile (a nonreserved lowercase C++ identifier),
canvas [width, height] (1..466), frames {name: relative PNG path}, and clips
{name: {steps: [{frame: name, duration_ms: 1..65535}], loop: bool}}.
Names contain only ASCII letters, digits, underscores and hyphens. Frames and
clips are nonempty; scene/provenance JSON metadata is retained without changes.
Getters use sorted frame/clip indices, recorded in manifest.json. No cropping,
resizing, compositing or runtime decoding is performed. Each frame replaces the
full original canvas: consumers MUST clear it or restore its backdrop first.
Pillow is required only on the exporting host (the images extra).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import struct
from pathlib import Path


_KEYWORDS = set("""alignas alignof and and_eq asm auto bitand bitor bool break
case catch char char8_t char16_t char32_t class compl concept const consteval
constexpr constinit const_cast continue co_await co_return co_yield decltype
default delete do double dynamic_cast else enum explicit export extern false
float for friend goto if inline int long mutable namespace new noexcept not
not_eq nullptr operator or or_eq private protected public register reinterpret_cast
requires return short signed sizeof static static_assert static_cast struct switch
template this thread_local throw true try typedef typeid typename union unsigned
using virtual void volatile wchar_t while xor xor_eq""".split())


def generate(profile_path: Path, assets_root: Path, out_dir: Path) -> dict:
    """Validate all inputs before creating a new output; return its manifest.

    Existing outputs are never changed. Payload budgets count unique pixel/mask
    bytes only, excluding C++ pointer/struct metadata and duplicated binary files.
    RGB for masked-out pixels in retained tiles is preserved; fully transparent
    tiles are omitted, so their invisible RGB cannot be reconstructed.
    """
    from PIL import Image

    profile_path, assets_root, out_dir = map(Path, (profile_path, assets_root, out_dir))
    root, output = assets_root.resolve(), out_dir.resolve()
    if (output.is_relative_to(root) or root.is_relative_to(output)
            or profile_path.resolve().is_relative_to(output)):
        raise ValueError("output must be outside the input tree")
    if out_dir.exists() or out_dir.is_symlink():
        raise ValueError("output directory must be new")
    if not root.is_dir():
        raise ValueError("assets root must be a directory")
    try:
        profile_bytes = profile_path.read_bytes()
        data = json.loads(profile_bytes)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{profile_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("profile must be an object")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    profile = data.get("profile")
    if (not isinstance(profile, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", profile)
            or "__" in profile or profile in _KEYWORDS):
        raise ValueError("profile must be a safe lowercase C++ identifier")
    canvas = data.get("canvas")
    if (not isinstance(canvas, list) or len(canvas) != 2
            or any(type(side) is not int or not 1 <= side <= 466 for side in canvas)):
        raise ValueError("canvas must contain two integers in 1..466")
    width, height = canvas
    frames, clips = data.get("frames"), data.get("clips")
    for label, mapping in (("frames", frames), ("clips", clips)):
        if not isinstance(mapping, dict) or not mapping or len(mapping) > 65535:
            raise ValueError(f"{label} must be a nonempty object with at most 65535 entries")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in mapping):
            raise ValueError(f"{label}: unsafe name")
    frame_names, clip_names = sorted(frames), sorted(clips)
    frame_indices = {name: index for index, name in enumerate(frame_names)}
    for name in clip_names:
        clip = clips[name]
        if not isinstance(clip, dict) or type(clip.get("loop")) is not bool:
            raise ValueError(f"clip {name}: loop must be boolean")
        steps = clip.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 65535:
            raise ValueError(f"clip {name}: steps must contain 1..65535 entries")
        for step in steps:
            if (not isinstance(step, dict) or not isinstance(step.get("frame"), str)
                    or step["frame"] not in frames):
                raise ValueError(f"clip {name}: unknown frame reference")
            duration = step.get("duration_ms")
            if type(duration) is not int or not 1 <= duration <= 65535:
                raise ValueError(f"clip {name}: duration_ms must be integer 1..65535")

    tiles, tile_indices, frame_data = [], {}, {}
    files = {}
    for name in frame_names:
        relative = frames[name]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"frame {name}: source must be a relative path")
        source_path = (root / relative).resolve()
        if not source_path.is_relative_to(root):
            raise ValueError(f"frame {name}: source must be within assets root")
        try:
            source_bytes = source_path.read_bytes()
            with Image.open(io.BytesIO(source_bytes)) as source:
                if source.format != "PNG" or source.size != (width, height):
                    raise ValueError(f"expected {width}x{height} PNG")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("expected a single-frame PNG")
                image = source.convert("RGBA")
        except (OSError, ValueError) as exc:
            raise ValueError(f"{source_path}: {exc}") from exc
        colors, refs = image.load(), []
        for y0 in range(0, height, 16):
            for x0 in range(0, width, 16):
                tw, th = min(16, width - x0), min(16, height - y0)
                values, mask = [], bytearray(((tw + 7) // 8) * th)
                for y in range(th):
                    for x in range(tw):
                        r, g, b, alpha = colors[x0 + x, y0 + y]
                        values.append(((r * 31 + 127) // 255 << 11)
                                      | ((g * 63 + 127) // 255 << 5)
                                      | ((b * 31 + 127) // 255))
                        if alpha >= 128:
                            mask[y * ((tw + 7) // 8) + x // 8] |= 0x80 >> (x % 8)
                if not any(mask):
                    continue
                pixels = struct.pack(f"<{len(values)}H", *values)
                key = (tw, th, pixels, bytes(mask))
                if key not in tile_indices:
                    index = len(tiles)
                    tile_indices[key] = index
                    pixel_file, mask_file = f"tile-{index:04d}.pixels.bin", f"tile-{index:04d}.alpha.bin"
                    tiles.append({"index": index, "width": tw, "height": th,
                                  "pixels": pixel_file, "mask": mask_file})
                    files[pixel_file], files[mask_file] = pixels, bytes(mask)
                refs.append({"x": x0, "y": y0, "tile": tile_indices[key]})
        frame_data[name] = {"index": frame_indices[name], "width": width, "height": height,
                            "source": relative, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "tiles": refs}

    namespace = f"hg::portrait_assets::{profile}"
    header = ["// Generated portrait assets; source rights remain with their owners.",
              "#pragma once", '#include "hg/portrait_assets.hpp"', "",
              f"namespace {namespace} {{", "const Frame* frame(size_t index);",
              "const Clip* clip(size_t index);", f"}}  // namespace {namespace}", ""]
    lines = ['#include "assets.hpp"', "", f"namespace {namespace} {{", "namespace {"]
    for tile in tiles:
        index = tile["index"]
        for suffix, ctype, values, digits in (
            ("pixels", "uint16_t", struct.unpack(f'<{tile["width"] * tile["height"]}H', files[tile["pixels"]]), 4),
            ("mask", "uint8_t", files[tile["mask"]], 2),
        ):
            lines.append(f"static constexpr {ctype} kTile{index}_{suffix}[] = {{")
            for start in range(0, len(values), 12):
                lines.append("  " + ", ".join(f"0x{v:0{digits}x}" for v in values[start:start + 12]) + ",")
            lines.append("};")
        lines.append(f'static constexpr Bitmap kTile{index} = '
                     f'{{{tile["width"]}, {tile["height"]}, kTile{index}_pixels, kTile{index}_mask}};')
    for name in frame_names:
        frame = frame_data[name]
        index, refs = frame["index"], frame["tiles"]
        if refs:
            lines.append(f"static constexpr TileRef kRefs{index}[] = {{")
            lines.extend(f'  {{{ref["x"]}, {ref["y"]}, &kTile{ref["tile"]}}},' for ref in refs)
            lines.append("};")
    lines.append("static constexpr Frame kFrames[] = {")
    for name in frame_names:
        frame = frame_data[name]
        pointer = f'kRefs{frame["index"]}' if frame["tiles"] else "nullptr"
        lines.append(f'  {{{width}, {height}, {pointer}, {len(frame["tiles"])}}},')
    lines.append("};")
    for index, name in enumerate(clip_names):
        lines.append(f"static constexpr Step kSteps{index}[] = {{")
        lines.extend(f'  {{&kFrames[{frame_indices[step["frame"]]}], {step["duration_ms"]}}},'
                     for step in clips[name]["steps"])
        lines.append("};")
    lines.append("static constexpr Clip kClips[] = {")
    lines.extend(f'  {{kSteps{index}, {len(clips[name]["steps"])}, {str(clips[name]["loop"]).lower()}}},'
                 for index, name in enumerate(clip_names))
    lines.extend(["};", "}  // namespace",
                  f"const Frame* frame(size_t index) {{ return index < {len(frames)} ? &kFrames[index] : nullptr; }}",
                  f"const Clip* clip(size_t index) {{ return index < {len(clips)} ? &kClips[index] : nullptr; }}",
                  f"}}  // namespace {namespace}", ""])
    rgb_bytes = sum(len(files[tile["pixels"]]) for tile in tiles)
    mask_bytes = sum(len(files[tile["mask"]]) for tile in tiles)
    naive = len(frames) * (width * height * 2 + ((width + 7) // 8) * height)
    report = {
        "schema_version": 1, "profile": profile, "canvas": canvas,
        "metadata": {key: value for key, value in data.items()
                     if key not in {"schema_version", "profile", "canvas", "frames", "clips"}},
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "frames": frame_data,
        "clips": {name: {**clips[name], "index": index} for index, name in enumerate(clip_names)},
        "tiles": tiles,
        "encoding": {"pixels": "RGB565", "endian": "little", "mask": "MSB-first 1-bit, byte-padded rows",
                     "alpha_threshold": 128, "tile_size": 16},
        "rendering": {"full_canvas_replacement": True, "requires_clear_or_backdrop": True,
                      "requirement": "Clear or restore the entire canvas before every frame; omitted tiles must not leave old mouths or other pixels behind."},
        "budget": {"rgb565_bytes": rgb_bytes, "mask_bytes": mask_bytes,
                   "payload_bytes": rgb_bytes + mask_bytes, "naive_fullframe_bytes": naive,
                   "saved_bytes": naive - rgb_bytes - mask_bytes,
                   "excludes": "C++ metadata, source text, and duplicate binary storage"},
    }
    files["assets.hpp"] = "\n".join(header).encode("ascii")
    files["assets.cpp"] = "\n".join(lines).encode("ascii")
    files["manifest.json"] = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    # Exclusive creation also prevents replacing an output created during validation.
    out_dir.mkdir()
    try:
        for filename, payload in files.items():
            (out_dir / filename).write_bytes(payload)
    except BaseException:
        shutil.rmtree(out_dir)
        raise
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = generate(args.profile, args.assets, args.out)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, f"portrait-assets: {exc}\n")
    print(json.dumps({"profile": report["profile"], "frames": len(report["frames"]),
                      "clips": len(report["clips"]), "tiles": len(report["tiles"]),
                      "budget": report["budget"], "output": str(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
