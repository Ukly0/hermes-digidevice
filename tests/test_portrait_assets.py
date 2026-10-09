"""Synthetic artwork only; never access private character assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import pytest

Image = pytest.importorskip("PIL.Image", reason="portrait conversion requires Pillow")

from hermes_gadget.portrait_assets import generate  # noqa: E402


@pytest.fixture
def artwork(tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    # Two shared full tiles, a nine-pixel-wide partial tile and empty bottom tiles.
    image = Image.new("RGBA", (41, 19))
    for y in range(16):
        for x in range(16):
            color = (x * 13, y * 11, 5, (0, 127, 128, 255)[(x + y) % 4])
            image.putpixel((x, y), color)
            image.putpixel((16 + x, y), color)
    for y in range(3):
        for x in range(9):
            image.putpixel((32 + x, y), (5, 3, 128, 128 if x in (0, 8) else 127))
    image.save(root / "a.png")
    image.save(root / "b.png")
    Image.new("RGBA", image.size, (255, 23, 65, 127)).save(root / "empty.png")
    profile = root / "profile.json"
    data = {
        "schema_version": 1, "profile": "synthetic", "canvas": [41, 19],
        "frames": {"left-rest-0": "a.png", "left_rest_1": "b.png", "empty": "empty.png"},
        "clips": {"left-rest": {"steps": [{"frame": "left-rest-0", "duration_ms": 1800},
                                           {"frame": "left_rest_1", "duration_ms": 60},
                                           {"frame": "empty", "duration_ms": 65535}], "loop": True}},
        "scene": {"backdrop": "synthetic-only"}, "provenance": {"author": "test fixture"},
    }
    profile.write_text(json.dumps(data))
    return root, profile, data


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


def rgb565(color):
    r, g, b = color[:3]
    return ((r * 31 + 127) // 255 << 11) | ((g * 63 + 127) // 255 << 5) | ((b * 31 + 127) // 255)


def test_decode_registration_dedup_budget_and_determinism(artwork, tmp_path):
    root, profile, data = artwork
    before = snapshot(root)
    out = tmp_path / "generated"
    report = generate(profile, root, out)
    assert json.loads((out / "manifest.json").read_text()) == report
    assert report["metadata"] == {"scene": data["scene"], "provenance": data["provenance"]}
    assert report["profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    assert report["rendering"]["requires_clear_or_backdrop"] is True
    assert report["rendering"]["full_canvas_replacement"] is True
    assert report["encoding"]["endian"] == "little"
    assert len(report["tiles"]) == 2
    assert [(t["width"], t["height"]) for t in report["tiles"]] == [(16, 16), (9, 16)]
    refs = report["frames"]["left-rest-0"]["tiles"]
    assert refs == [{"x": 0, "y": 0, "tile": 0}, {"x": 16, "y": 0, "tile": 0},
                    {"x": 32, "y": 0, "tile": 1}]
    assert report["frames"]["left_rest_1"]["tiles"] == refs
    assert report["frames"]["empty"]["tiles"] == []
    payload = 0
    cpp = (out / "assets.cpp").read_text()
    for tile in report["tiles"]:
        tw, th = tile["width"], tile["height"]
        raw, mask = (out / tile["pixels"]).read_bytes(), (out / tile["mask"]).read_bytes()
        payload += len(raw) + len(mask)
        assert len(raw) == tw * th * 2
        assert len(mask) == ((tw + 7) // 8) * th
        for suffix, expected in (("pixels", struct.unpack(f"<{tw * th}H", raw)), ("mask", mask)):
            body = re.search(rf'kTile{tile["index"]}_{suffix}\[\] = \{{(.*?)\}};', cpp, re.S)[1]
            assert tuple(int(value, 16) for value in re.findall(r"0x([0-9a-f]+)", body)) == tuple(expected)
        if tw == 9:
            assert mask[:6] == b"\x80\x80" * 3
            assert mask[6:] == bytes(26)
    for name, frame in report["frames"].items():
        assert (frame["width"], frame["height"]) == (41, 19)
        source = root / data["frames"][name]
        assert frame["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        with Image.open(source) as image:
            expected = image.convert("RGBA")
        reconstructed_pixels, reconstructed_mask = [0] * (41 * 19), [False] * (41 * 19)
        retained = set()
        for ref in frame["tiles"]:
            tile = report["tiles"][ref["tile"]]
            tw, th = tile["width"], tile["height"]
            values = struct.unpack(f"<{tw * th}H", (out / tile["pixels"]).read_bytes())
            mask = (out / tile["mask"]).read_bytes()
            for y in range(th):
                for x in range(tw):
                    xy = (ref["x"] + x, ref["y"] + y)
                    i = xy[1] * 41 + xy[0]
                    retained.add(xy)
                    reconstructed_pixels[i] = values[y * tw + x]
                    reconstructed_mask[i] = bool(mask[y * ((tw + 7) // 8) + x // 8] & (0x80 >> (x % 8)))
        for y in range(19):
            for x in range(41):
                color = expected.getpixel((x, y))
                assert reconstructed_mask[y * 41 + x] == (color[3] >= 128)
                if (x, y) in retained:
                    assert reconstructed_pixels[y * 41 + x] == rgb565(color)
    assert report["budget"]["payload_bytes"] == payload == 16 * 16 * 2 + 32 + 9 * 16 * 2 + 32
    assert report["budget"]["naive_fullframe_bytes"] == 3 * (41 * 19 * 2 + 6 * 19)
    assert report["budget"]["saved_bytes"] == report["budget"]["naive_fullframe_bytes"] - payload
    assert snapshot(root) == before
    other = tmp_path / "second"
    assert generate(profile, root, other) == report
    assert snapshot(out) == snapshot(other)
    previous = snapshot(out)
    with pytest.raises(ValueError, match="new"):
        generate(profile, root, out)
    assert snapshot(out) == previous


@pytest.mark.parametrize("key,value", [
    ("schema_version", True), ("schema_version", 2), ("schema_version", "1"),
    ("profile", "Gatomon"), ("profile", "namespace"), ("profile", "bad-name"),
    ("profile", "_reserved"), ("profile", "bad__name"), ("profile", 1),
    ("canvas", [True, 19]), ("canvas", [41, 19.0]), ("canvas", [0, 19]),
    ("canvas", [467, 19]), ("canvas", [41]), ("canvas", "41x19"),
    ("frames", {}), ("frames", []), ("frames", {"bad/name": "a.png"}),
    ("frames", {"caf\u00e9": "a.png"}), ("frames", {"a": 1}),
    ("clips", {}), ("clips", []), ("clips", {"bad/name": {}}),
])
def test_invalid_schema_no_writes(artwork, tmp_path, key, value):
    root, profile, data = artwork
    data[key] = value
    profile.write_text(json.dumps(data))
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        generate(profile, root, tmp_path / "out")
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("field,value", [
    ("duration_ms", 0), ("duration_ms", 65536), ("duration_ms", True),
    ("duration_ms", 1.0), ("duration_ms", "60"), ("frame", "missing"),
    ("frame", 1), ("frame", []),
])
def test_invalid_steps_no_partial_write(artwork, tmp_path, field, value):
    root, profile, data = artwork
    data["clips"]["left-rest"]["steps"][-1][field] = value
    profile.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        generate(profile, root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("clip", [None, {}, {"loop": 1, "steps": []},
                                  {"loop": False, "steps": []},
                                  {"loop": False, "steps": [None]},
                                  {"loop": False, "steps": "bad"}])
def test_invalid_clips(artwork, tmp_path, clip):
    root, profile, data = artwork
    data["clips"]["left-rest"] = clip
    profile.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        generate(profile, root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("failure", ["missing", "corrupt", "size", "format", "animated"])
def test_invalid_last_image_no_partial_write(artwork, tmp_path, failure):
    root, profile, _ = artwork
    path = root / "b.png"
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_bytes(b"not a PNG")
    elif failure == "size":
        Image.new("RGBA", (40, 19)).save(path)
    elif failure == "animated":
        Image.new("RGBA", (41, 19)).save(path, save_all=True,
                                        append_images=[Image.new("RGBA", (41, 19), "red")])
    else:
        Image.new("RGB", (41, 19)).save(path, format="BMP")
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        generate(profile, root, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("failure", ["traversal", "absolute", "source_symlink", "output_inside",
                                     "output_symlink", "output_ancestor", "existing", "dangling"])
def test_path_safety(artwork, tmp_path, failure):
    root, profile, data = artwork
    outside = tmp_path / "outside.png"
    Image.new("RGBA", (41, 19), "red").save(outside)
    out = tmp_path / "out"
    if failure == "traversal":
        data["frames"]["left-rest-0"] = "../outside.png"
    elif failure == "absolute":
        data["frames"]["left-rest-0"] = str(outside)
    elif failure == "source_symlink":
        (root / "escape.png").symlink_to(outside)
        data["frames"]["left-rest-0"] = "escape.png"
    elif failure == "output_inside":
        out = root / "out"
    elif failure == "output_symlink":
        (tmp_path / "alias").symlink_to(root, target_is_directory=True)
        out = tmp_path / "alias/out"
    elif failure == "output_ancestor":
        out = tmp_path
    elif failure == "dangling":
        out.symlink_to(tmp_path / "nonexistent")
    else:
        out.mkdir()
        (out / "previous").write_bytes(b"keep me")
    profile.write_text(json.dumps(data))
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        generate(profile, root, out)
    assert snapshot(tmp_path) == before
    if failure == "dangling":
        assert out.is_symlink()


def test_tile_dimensions_participate_in_dedup(artwork, tmp_path):
    root, profile, data = artwork
    # 16x8 and 8x16 have identical encoded pixels/masks but different shapes.
    data["canvas"] = [24, 24]
    for name in data["frames"].values():
        Image.new("RGBA", (24, 24), (0, 0, 0, 255)).save(root / name)
    profile.write_text(json.dumps(data))
    report = generate(profile, root, tmp_path / "out")
    assert {(t["width"], t["height"]) for t in report["tiles"]} == {(16, 16), (8, 16), (16, 8), (8, 8)}
    assert len(report["tiles"]) == 4
    side_tiles = [tile for tile in report["tiles"] if tile["width"] != tile["height"]]
    for field in ("pixels", "mask"):
        assert (tmp_path / "out" / side_tiles[0][field]).read_bytes() == (tmp_path / "out" / side_tiles[1][field]).read_bytes()


@pytest.mark.parametrize("change", ["rgb", "mask"])
def test_dedup_compares_pixels_and_masks(artwork, tmp_path, change):
    root, profile, _ = artwork
    with Image.open(root / "b.png") as source:
        image = source.convert("RGBA")
    r, g, b, alpha = image.getpixel((0, 0))
    image.putpixel((0, 0), (255, g, b, alpha) if change == "rgb" else (r, g, b, 255))
    image.save(root / "b.png")
    report = generate(profile, root, tmp_path / "out")
    assert len(report["tiles"]) == 3
    refs = report["frames"]["left_rest_1"]["tiles"]
    assert [(ref["x"], ref["y"]) for ref in refs] == [(0, 0), (16, 0), (32, 0)]
    assert refs[0]["tile"] != refs[1]["tile"]
    assert refs[1:] == report["frames"]["left-rest-0"]["tiles"][1:]


@pytest.mark.parametrize("canvas", [[1, 1], [466, 466]])
def test_canvas_limits_and_minimum_duration(artwork, tmp_path, canvas):
    root, profile, data = artwork
    data["canvas"] = canvas
    data["clips"]["left-rest"]["steps"][0]["duration_ms"] = 1
    for name in data["frames"].values():
        Image.new("RGBA", tuple(canvas), (5, 3, 5, 128)).save(root / name)
    profile.write_text(json.dumps(data))
    report = generate(profile, root, tmp_path / "out")
    assert report["canvas"] == canvas
    assert report["clips"]["left-rest"]["steps"][0]["duration_ms"] == 1


@pytest.mark.parametrize("contents", ["{", "[]", "null", "true"])
def test_invalid_profile_json_no_output(artwork, tmp_path, contents):
    root, profile, _ = artwork
    profile.write_text(contents)
    with pytest.raises(ValueError):
        generate(profile, root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("empty", [False, True])
def test_generated_cpp_contract(artwork, tmp_path, empty):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++17 compiler not installed")
    root, profile, data = artwork
    if empty:
        for name in data["frames"].values():
            Image.new("RGBA", (41, 19)).save(root / name)
        data["clips"]["left-rest"]["loop"] = False
        profile.write_text(json.dumps(data))
    out = tmp_path / "out"
    report = generate(profile, root, out)
    assert not empty or report["tiles"] == []
    main = tmp_path / "main.cpp"
    main.write_text(f"""
#include "assets.hpp"
#include <cassert>
int main() {{
  using namespace hg::portrait_assets::synthetic;
  assert(!frame(3) && !clip(1));
  assert(!frame(static_cast<size_t>(-1)) && !clip(static_cast<size_t>(-1)));
  assert(frame(0)->width == 41 && frame(0)->height == 19);
  assert(frame(0)->count == 0 && frame(0)->tiles == nullptr);
  assert(clip(0)->count == 3 && clip(0)->loop == {str(not empty).lower()});
  assert(clip(0)->steps[0].frame == frame(1));
  assert(clip(0)->steps[0].duration_ms == 1800);
  assert(clip(0)->steps[1].duration_ms == 60);
  assert(clip(0)->steps[2].duration_ms == 65535);
  assert(frame(1)->count == {0 if empty else 3});
  {'assert(frame(1)->tiles == nullptr);' if empty else 'assert(frame(1)->tiles[0].bitmap == frame(1)->tiles[1].bitmap);'}
}}
""", encoding="ascii")
    include = Path(__file__).resolve().parents[1] / "firmware/core/include"
    executable = tmp_path / "check"
    subprocess.run([compiler, "-std=c++17", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
                    "-fno-exceptions", "-fno-rtti", "-I", str(include), "-I", str(out),
                    str(out / "assets.cpp"), str(main), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)


def test_cli(artwork, tmp_path):
    root, profile, _ = artwork
    command = [sys.executable, "-m", "hermes_gadget.portrait_assets"]
    for arguments in ([], ["--profile", str(profile), "--assets", str(root)]):
        assert subprocess.run(command + arguments, capture_output=True).returncode == 2
    arguments = ["--profile", str(profile), "--assets", str(root), "--out", str(tmp_path / "out")]
    result = subprocess.run(command + arguments, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["budget"]["payload_bytes"] > 0
    before = snapshot(tmp_path / "out")
    result = subprocess.run(command + arguments, capture_output=True, text=True)
    assert result.returncode == 1
    assert "must be new" in result.stderr
    assert snapshot(tmp_path / "out") == before
