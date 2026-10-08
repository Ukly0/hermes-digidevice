"""Synthetic artwork only: no private pixels are needed or copied by tests."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

Image = pytest.importorskip("PIL.Image", reason="asset conversion requires Pillow")
ImageFont = pytest.importorskip("PIL.ImageFont")

from hermes_gadget import habitat_assets  # noqa: E402


@pytest.fixture
def artwork(tmp_path):
    assets = tmp_path / "assets"
    font = assets / "fonts/pixel-digivolve/Pixel Digivolve.otf"
    font.parent.mkdir(parents=True)
    # Pillow's bundled test face, not private Digivolve material.
    font.write_bytes(ImageFont.load_default(size=18).path.getvalue())
    # Keep the fixture independent of the converter's ordering constants.
    for resident, (name, base) in enumerate((
        ("agumon", 248), ("gabumon", 282), ("biyomon", 316), ("tentomon", 338),
        ("palmon", 360), ("gomamon", 382), ("patamon", 404), ("gatomon", 428),
    )):
        source = assets / name / "source"
        source.mkdir(parents=True)
        for pose, offset in enumerate((0, 1, 7, 6, 2, 3, 4, 5)):
            image = Image.new("RGBA", (64, 64))
            image.putpixel((10, 20), (resident * 32, pose * 32, 255, 255))
            image.save(source / f"{base + offset}_0_0.png")
    background = assets / "environments" / "beach-island"
    background.mkdir(parents=True)
    Image.new("RGB", (384, 128), (255, 0, 0)).save(background / "layer_base.png")
    for filename, top, bottom, color in (
        ("layer_water.png", 108, 128, (0, 0, 255, 255)),
        ("layer_sand_sea.png", 94, 108, (0, 255, 0, 255)),
    ):
        image = Image.new("RGBA", (384, 128))
        image.paste(color, (0, top, 384, bottom))
        image.save(background / filename)
    icons = assets / "icons" / "source"
    icons.mkdir(parents=True)
    for index, (filename, size) in enumerate((
        ("7_0_0.png", (32, 16)), ("16_0_0.png", (64, 64)),
        ("17_0_0.png", (32, 32)), ("17_1_0.png", (24, 12)),
    )):
        image = Image.new("RGBA", size)
        image.putpixel((index + 2, index + 3), (255, index * 32, 0, 255))
        image.save(icons / filename)
    return assets


def array(text, index, suffix):
    body = re.search(rf"k{index}_{suffix}\[\] = \{{(.*?)\}};", text, re.S)
    assert body is not None
    return [int(value, 16) for value in re.findall(r"0x([0-9a-f]+)", body[1])]


def test_order_payload_budget_and_sources_unchanged(artwork, tmp_path):
    before = {path: path.read_bytes() for path in artwork.rglob("*.png")}
    out = tmp_path / "assets.cpp"
    result = habitat_assets.generate(artwork, out)
    text = out.read_text(encoding="ascii")
    font_bytes = sum(len(re.findall(r"0x[0-9a-f]+", body)) for body in
                     re.findall(r"kFont\d+_\d+\[\] = \{(.*?)\};", text, re.S))
    assert result == {
        "residents": 8, "frames": 64, "backgrounds": 1, "icons": 4, "layers": 2,
        "fonts": 2, "glyphs": 190, "font_bytes": font_bytes,
        "rgb565_bytes": 384 * (128 + 34) * 2 + 68 * 2,
        "mask_bytes": 68 + 48 * 34,
        "total_bytes": 384 * (128 + 34) * 2 + 68 * 3 + 48 * 34 + font_bytes,
    }
    for resident in range(8):
        for pose in range(8):
            index = resident * 8 + pose
            assert array(text, index, "pixels") == [
                ((resident * 32 * 31 + 127) // 255 << 11)
                | ((pose * 32 * 63 + 127) // 255 << 5) | 31
            ]
            assert array(text, index, "mask") == [0x80]
            assert f"{{1, 1, k{index}_pixels, k{index}_mask}}" in text
    assert "kFrames[8][8]" in text
    assert array(text, 64, "pixels") == [0xf800] * (384 * 128)
    assert "{384, 128, k64_pixels, nullptr}" in text
    assert "k64_mask" not in text
    assert "static constexpr Layer kLayers[2]" in text
    for index, height, y, color in ((69, 20, 108, 0x001f), (70, 14, 94, 0x07e0)):
        assert f"{{{{384, {height}, k{index}_pixels, k{index}_mask}}, 0, {y}}}" in text
        assert array(text, index, "pixels") == [color] * (384 * height)
        assert array(text, index, "mask") == [0xff] * (48 * height)
    assert result["rgb565_bytes"] == sum(len(array(text, i, "pixels")) * 2 for i in range(71))
    assert result["mask_bytes"] == sum(len(array(text, i, "mask")) for i in range(71) if i != 64)
    for index in range(4):
        assert array(text, 65 + index, "pixels") == [
            0xf800 | ((index * 32 * 63 + 127) // 255 << 5)
        ]
        assert array(text, 65 + index, "mask") == [0x80]
        assert f"{{1, 1, k{65 + index}_pixels, k{65 + index}_mask}}" in text
    assert {path: path.read_bytes() for path in before} == before
    habitat_assets.generate(artwork, out)
    assert out.read_text() == text


def test_common_bounds_source_alignment_and_no_attack_or_back(artwork, tmp_path):
    for pose, offset in enumerate((0, 1, 7, 6, 2, 3, 4, 5)):
        image = Image.new("RGBA", (64, 64))
        image.putpixel((4 + pose, 8 + pose), (0, pose * 32, 255, 255))
        image.putpixel((4 + pose + pose % 3, 8 + pose + pose % 2),
                       (0, pose * 32, 255, 255))
        if pose == 7:
            image.putpixel((2, 3), (255, 0, 0, 1))
        image.save(artwork / "agumon/source" / f"{248 + offset}_0_0.png")
    # These full-canvas poses must neither affect the crop nor be exported.
    for offset in (8, 11):
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(
            artwork / "agumon/source" / f"{248 + offset}_0_0.png")
    out = tmp_path / "assets.cpp"
    result = habitat_assets.generate(artwork, out)
    text = out.read_text()
    # Union (2, 3, 13, 17) includes alpha 1 in moveB, not just masked pixels.
    for pose in range(8):
        assert f"{{11, 14, k{pose}_pixels, k{pose}_mask}}" in text
        pixels, mask = [0] * (11 * 14), [0] * (2 * 14)
        color = ((pose * 32 * 63 + 127) // 255 << 5) | 31
        for x, y in {(4 + pose, 8 + pose),
                     (4 + pose + pose % 3, 8 + pose + pose % 2)}:
            x, y = x - 2, y - 3
            pixels[y * 11 + x] = color
            mask[y * 2 + x // 8] |= 0x80 >> (x % 8)
        if pose == 7:
            pixels[0] = 0xf800  # Included in bounds and RGB, excluded from mask.
        assert array(text, pose, "pixels") == pixels
        assert array(text, pose, "mask") == mask
    assert result["rgb565_bytes"] == 384 * (128 + 34) * 2 + 60 * 2 + 8 * 11 * 14 * 2
    assert result["mask_bytes"] == 60 + 8 * 2 * 14 + 48 * 34
    assert result["total_bytes"] == (result["rgb565_bytes"] + result["mask_bytes"]
                                     + result["font_bytes"])
    for offset in (8, 11):
        (artwork / "agumon/source" / f"{248 + offset}_0_0.png").write_bytes(b"not PNG")
    assert habitat_assets.generate(artwork, out) == result
    assert out.read_text() == text


def test_alpha_crop_threshold_row_padding_and_nearest_color(artwork, tmp_path):
    for offset in (1, 7, 6, 2, 3, 4, 5):
        image = Image.new("RGBA", (64, 64))
        image.putpixel((2, 3), (255, 255, 255, 255))
        image.save(artwork / "agumon/source" / f"{248 + offset}_0_0.png")
    image = Image.new("RGBA", (64, 64))
    image.putpixel((2, 3), (255, 0, 0, 128))
    image.putpixel((3, 3), (0, 255, 0, 127))
    image.putpixel((10, 3), (0, 0, 255, 255))
    image.putpixel((3, 4), (128, 128, 128, 255))
    image.putpixel((4, 4), (5, 3, 5, 255))
    image.putpixel((10, 4), (0, 0, 0, 1))
    image.save(artwork / "agumon/source/248_0_0.png")
    out = tmp_path / "assets.cpp"
    result = habitat_assets.generate(artwork, out)
    text = out.read_text()
    assert "{9, 2, k0_pixels, k0_mask}" in text
    assert array(text, 0, "mask") == [0x80, 0x80, 0x60, 0x00]
    pixels = array(text, 0, "pixels")
    assert len(pixels) == 18
    assert pixels[:2] == [0xf800, 0x07e0]
    assert pixels[8] == 0x001f
    assert pixels[10] == 0x8410
    assert pixels[11] == 0x0821  # Nearest representable color, not truncation.
    for pose in range(8):
        assert f"{{9, 2, k{pose}_pixels, k{pose}_mask}}" in text
    assert result["mask_bytes"] == 60 + 8 * 4 + 48 * 34
    assert result["rgb565_bytes"] == 384 * (128 + 34) * 2 + 60 * 2 + 8 * 18 * 2


def test_icons_independent_crop_alpha_and_row_padding(artwork, tmp_path):
    image = Image.new("RGBA", (20, 8))
    image.putpixel((2, 3), (255, 0, 0, 128))
    image.putpixel((3, 3), (0, 255, 0, 127))
    image.putpixel((10, 3), (0, 0, 255, 255))
    image.putpixel((3, 4), (128, 128, 128, 255))
    image.putpixel((4, 4), (5, 3, 5, 255))
    image.putpixel((10, 4), (0, 0, 0, 1))
    image.save(artwork / "icons/source/7_0_0.png")
    out = tmp_path / "assets.cpp"
    result = habitat_assets.generate(artwork, out)
    text = out.read_text()
    assert "{9, 2, k65_pixels, k65_mask}" in text
    assert array(text, 65, "mask") == [0x80, 0x80, 0x60, 0x00]
    pixels = [0] * 18
    pixels[0], pixels[1], pixels[8] = 0xf800, 0x07e0, 0x001f
    pixels[10], pixels[11] = 0x8410, 0x0821
    assert array(text, 65, "pixels") == pixels
    for index in range(66, 69):
        assert f"{{1, 1, k{index}_pixels, k{index}_mask}}" in text
    assert result["rgb565_bytes"] == 384 * (128 + 34) * 2 + (64 + 3 + 18) * 2
    assert result["mask_bytes"] == 64 + 3 + 4 + 48 * 34


def test_layer_fixed_bands_alpha_and_source_rgb_difference(artwork, tmp_path):
    environment = artwork / "environments/beach-island"
    for filename, top in (("layer_water.png", 108), ("layer_sand_sea.png", 94)):
        image = Image.new("RGBA", (384, 128), (255, 255, 255, 255))
        image.paste((0, 0, 0, 0), (0, top, 384, 128 if top == 108 else 108))
        # Base-identical RGB with different alpha must not move static beach.
        image.putpixel((0, top), (255, 0, 0, 128))
        image.putpixel((1, top), (0, 255, 0, 127))
        image.putpixel((2, top), (0, 0, 255, 128))
        # Different source RGB that rounds to the same RGB565 as the base.
        image.putpixel((7, top), (254, 0, 0, 255))
        image.putpixel((8, top + 1), (0, 255, 0, 255))
        image.putpixel((383, (127 if top == 108 else 107)), (255, 255, 255, 255))
        image.save(environment / filename)
    out = tmp_path / "assets.cpp"
    habitat_assets.generate(artwork, out)
    text = out.read_text()
    for index, height in ((69, 20), (70, 14)):
        mask = [0] * (48 * height)
        mask[0] = 0xa1 if index == 69 else 0x21
        mask[49] = 0x80
        mask[-1] = 0x01
        assert array(text, index, "mask") == mask
        pixels = [0] * (384 * height)
        pixels[0], pixels[1], pixels[2], pixels[7] = 0xf800, 0x07e0, 0x001f, 0xf800
        pixels[392], pixels[-1] = 0x07e0, 0xffff
        assert array(text, index, "pixels") == pixels


def test_opaque_base_identical_shoreline_allows_zero_difference_mask(artwork, tmp_path):
    # Meaningful source alpha is required, but no RGB differences is valid.
    path = artwork / "environments/beach-island/layer_sand_sea.png"
    Image.new("RGBA", (384, 128), (255, 0, 0, 255)).save(path)
    out = tmp_path / "assets.cpp"
    assert habitat_assets.generate(artwork, out)["layers"] == 2
    text = out.read_text()
    assert array(text, 70, "mask") == [0] * (48 * 14)
    assert array(text, 70, "pixels") == [0xf800] * (384 * 14)


@pytest.mark.parametrize("filename,top,bottom", [
    ("layer_water.png", 108, 128), ("layer_sand_sea.png", 94, 108),
])
@pytest.mark.parametrize("failure", [
    "missing", "corrupt", "wrong_format", "wide", "short", "empty", "below_threshold",
    "empty_band", "below_threshold_band",
])
def test_invalid_layers_preserve_output(artwork, tmp_path, filename, top, bottom, failure):
    path = artwork / "environments/beach-island" / filename
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_bytes(b"not a PNG")
    elif failure == "wrong_format":
        Image.new("RGBA", (384, 128)).save(path, format="BMP")
    else:
        size = {"wide": (385, 128), "short": (384, 127)}.get(failure, (384, 128))
        alpha = {"empty": 0, "below_threshold": 127}.get(failure, 255)
        image = Image.new("RGBA", size, (0, 255, 0, alpha))
        if failure.endswith("_band"):
            image.paste((0, 255, 0, 127 if failure == "below_threshold_band" else 0),
                        (0, top, 384, bottom))
        image.save(path)
    before = {source: source.read_bytes() for source in artwork.rglob("*.png")}
    out = tmp_path / "assets.cpp"
    out.write_bytes(b"previous valid output")
    with pytest.raises(ValueError, match=re.escape(str(path))):
        habitat_assets.generate(artwork, out)
    assert out.read_bytes() == b"previous valid output"
    out.unlink()
    with pytest.raises(ValueError, match=re.escape(str(path))):
        habitat_assets.generate(artwork, out)
    assert not out.exists()
    assert set(tmp_path.iterdir()) == {artwork}
    assert {source: source.read_bytes() for source in before} == before


@pytest.mark.parametrize("failure", [
    "missing", "corrupt", "wrong_format", "wide", "tall", "empty", "below_threshold",
])
def test_invalid_icons_preserve_output(artwork, tmp_path, failure):
    path = artwork / "icons/source/17_1_0.png"
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_bytes(b"not a PNG")
    elif failure == "wrong_format":
        Image.new("RGB", (32, 32)).save(path, format="BMP")
    else:
        size = {"wide": (65, 32), "tall": (32, 65)}.get(failure, (32, 32))
        alpha = {"empty": 0, "below_threshold": 127}.get(failure, 255)
        Image.new("RGBA", size, (255, 0, 0, alpha)).save(path)
    out = tmp_path / "assets.cpp"
    out.write_bytes(b"previous valid output")
    with pytest.raises(ValueError, match=re.escape(str(path))):
        habitat_assets.generate(artwork, out)
    assert out.read_bytes() == b"previous valid output"
    out.unlink()
    with pytest.raises(ValueError, match=re.escape(str(path))):
        habitat_assets.generate(artwork, out)
    assert not out.exists()
    assert set(tmp_path.iterdir()) == {artwork}


@pytest.mark.parametrize("failure", [
    "missing", "corrupt", "wrong_format", "sprite_size", "empty", "below_threshold",
    "background_size", "background_alpha", "background_empty",
])
def test_invalid_assets_preserve_output(artwork, tmp_path, failure):
    # Fail at the last frame/background, after earlier frames were processed.
    path = artwork / "gatomon/source/433_0_0.png"
    if failure.startswith("background"):
        path = artwork / "environments/beach-island/layer_base.png"
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_bytes(b"not a PNG")
    elif failure == "wrong_format":
        Image.new("RGB", (64, 64)).save(path, format="BMP")
    else:
        size = (384, 128) if failure.startswith("background") else (64, 64)
        if failure.endswith("size"):
            size = (size[0] - 1, size[1])
        alpha = {"empty": 0, "below_threshold": 127,
                 "background_alpha": 254, "background_empty": 0}.get(failure, 255)
        Image.new("RGBA", size, (255, 0, 0, alpha)).save(path)
    out = tmp_path / "assets.cpp"
    out.write_bytes(b"previous valid output")
    with pytest.raises(ValueError, match=re.escape(str(path))):
        habitat_assets.generate(artwork, out)
    assert out.read_bytes() == b"previous valid output"
    out.unlink()
    with pytest.raises(ValueError):
        habitat_assets.generate(artwork, out)
    assert not out.exists()
    assert set(tmp_path.iterdir()) == {artwork}


def test_output_cannot_replace_input(artwork):
    path = artwork / "agumon/source/248_0_0.png"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="outside"):
        habitat_assets.generate(artwork, path)
    assert path.read_bytes() == before


def test_cli_requires_explicit_paths_and_reports_budget(artwork, tmp_path):
    command = [sys.executable, "-m", "hermes_gadget.habitat_assets"]
    for arguments in ([], ["--assets", str(artwork)], ["--out", str(tmp_path / "out.cpp")]):
        result = subprocess.run(command + arguments, capture_output=True, text=True)
        assert result.returncode == 2
    out = tmp_path / "out.cpp"
    result = subprocess.run(command + ["--assets", str(artwork), "--out", str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["frames"] == 64
    assert json.loads(result.stdout)["icons"] == 4
    assert json.loads(result.stdout)["layers"] == 2
    previous = out.read_bytes()
    (artwork / "agumon/source/248_0_0.png").unlink()
    result = subprocess.run(command + ["--assets", str(artwork), "--out", str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "248_0_0.png" in result.stderr
    assert out.read_bytes() == previous


def test_font_metrics_baseline_masks_and_sizes(artwork, tmp_path):
    from PIL import ImageDraw

    fonts = habitat_assets._fonts(artwork / habitat_assets.FONT)
    out = tmp_path / "assets.cpp"
    result = habitat_assets.generate(artwork, out)
    text = out.read_text(encoding="ascii")
    assert result["font_bytes"] == sum(len(glyph[-1]) for _, _, glyphs in fonts for glyph in glyphs)
    assert len(fonts) == 2
    for font_index, (size, (ascent, line_height, glyphs)) in enumerate(zip((18, 32), fonts)):
        font = ImageFont.truetype(str(artwork / habitat_assets.FONT), size=size)
        assert (ascent, line_height) == (font.getmetrics()[0], sum(font.getmetrics()))
        assert len(glyphs) == 95
        for code, (width, height, advance, x, y, bits) in enumerate(glyphs, start=32):
            char = chr(code)
            box = font.getbbox(char, anchor="ls")
            assert (width, height, x, y) == (box[2] - box[0], box[3] - box[1], *box[:2])
            assert advance == round(font.getlength(char))
            pointer = f"kFont{font_index}_{code}" if bits else "nullptr"
            assert f"{{{width}, {height}, {advance}, {x}, {y}, {pointer}}}" in text
            if not width or not height:
                assert not bits
                assert f"kFont{font_index}_{code}[]" not in text
                continue
            assert array(text, f"Font{font_index}", code) == list(bits)
            # Independently render on a baseline-aligned full canvas, then crop.
            canvas = Image.new("L", (256, 256))
            ImageDraw.Draw(canvas).text((64, 128), char, font=font, fill=255, anchor="ls")
            stride = (width + 7) // 8
            assert len(bits) == stride * height
            for row in range(height):
                for column in range(stride * 8):
                    actual = bool(bits[row * stride + column // 8] & (0x80 >> (column % 8)))
                    expected = column < width and canvas.getpixel((64 + x + column, 128 + y + row)) >= 128
                    assert actual == expected
        colon, digit = glyphs[ord(':') - 32], glyphs[ord('0') - 32]
        assert colon[4] > digit[4]  # Colon remains below the digit's top, not top-aligned.
        assert ascent + colon[4] > ascent + digit[4]
        assert glyphs[0][2] > 0 and not glyphs[0][-1]
    assert fonts[1][2][ord('M') - 32][1] > fonts[0][2][ord('M') - 32][1]


@pytest.mark.parametrize("failure", ["missing", "empty", "invalid", "large_size"])
def test_invalid_fonts_preserve_output(artwork, tmp_path, monkeypatch, failure):
    path = artwork / habitat_assets.FONT
    if failure == "missing":
        path.unlink()
    elif failure in ("empty", "invalid"):
        path.write_bytes(b"" if failure == "empty" else b"not a font")
    else:
        original = ImageFont.truetype

        def fail_large(path, size):
            if size == 32:
                raise OSError("cannot load nominal 32px")
            return original(path, size=size)

        monkeypatch.setattr(ImageFont, "truetype", fail_large)
    out = tmp_path / "assets.cpp"
    for previous in (b"previous valid output", None):
        if previous is not None:
            out.write_bytes(previous)
        else:
            out.unlink()
        with pytest.raises(ValueError, match=re.escape(str(path))):
            habitat_assets.generate(artwork, out)
        if previous is not None:
            assert out.read_bytes() == previous
        else:
            assert not out.exists()
            assert set(tmp_path.iterdir()) == {artwork}


@pytest.mark.parametrize("box", [(0, 0, 129, 1), (0, 0, 1, 129), (0, 0, -1, 1),
                                 (-32769, 0, -32768, 1), (0, 32768, 1, 32769)])
def test_font_bounds_preserve_output(artwork, tmp_path, monkeypatch, box):
    class BadFont:
        def getmetrics(self):
            return 18, 5

        def getbbox(self, char, anchor):
            return box

        def getlength(self, char):
            return 1

    monkeypatch.setattr(ImageFont, "truetype", lambda *args, **kwargs: BadFont())
    out = tmp_path / "assets.cpp"
    out.write_bytes(b"previous")
    with pytest.raises(ValueError, match="outside bounds"):
        habitat_assets.generate(artwork, out)
    assert out.read_bytes() == b"previous"


def test_font_threshold_padding_and_exact_size_limit(monkeypatch, tmp_path):
    from PIL import ImageDraw

    class Font:
        def getmetrics(self):
            return 128, 0

        def getbbox(self, char, anchor):
            assert anchor == "ls"
            return (-1, -128, 127, 0) if char == 'M' else (-1, -2, 8, 0)

        def getlength(self, char):
            return 9.6

    class Draw:
        def __init__(self, image):
            self.image = image

        def text(self, position, char, font, fill, anchor):
            assert position == (1, 128 if char == 'M' else 2)
            self.image.putpixel((0, 0), 127)
            self.image.putpixel((1, 0), 128)
            self.image.putpixel((8, 1), 255)

    monkeypatch.setattr(ImageFont, "truetype", lambda *args, **kwargs: Font())
    monkeypatch.setattr(ImageDraw, "Draw", Draw)
    fonts = habitat_assets._fonts(tmp_path / "synthetic.otf")
    for ascent, line_height, glyphs in fonts:
        assert (ascent, line_height) == (128, 128)
        assert glyphs[0] == (9, 2, 10, -1, -2, b"\x40\x00\x00\x80")
        assert glyphs[ord('M') - 32][:2] == (128, 128)
        assert len(glyphs[ord('M') - 32][-1]) == 16 * 128


def test_generated_cpp_contract(artwork, tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++17 compiler not installed")
    out = tmp_path / "assets.cpp"
    habitat_assets.generate(artwork, out)
    include = tmp_path / "hg"
    include.mkdir()
    (include / "habitat_assets.hpp").write_text("""
#pragma once
#include <stddef.h>
#include <stdint.h>
namespace hg::habitat_assets {
struct Bitmap { uint16_t width, height; const uint16_t* pixels; const uint8_t* mask; };
struct Layer { Bitmap bitmap; uint16_t x, y; };
struct Glyph { uint16_t width, height, advance; int16_t x_offset, y_offset; const uint8_t* bits; };
enum FontSize : size_t { Small, Large, FontCount };
const Glyph* glyph(size_t font, unsigned char character);
uint16_t ascent(size_t font);
uint16_t line_height(size_t font);
const Bitmap* frame(size_t resident, size_t pose);
const Bitmap* background();
const Bitmap* icon(size_t index);
const Layer* layer(size_t index);
bool available();
}
""", encoding="ascii")
    main = tmp_path / "main.cpp"
    main.write_text("""
#include "hg/habitat_assets.hpp"
#include <cassert>
int main() {
    using namespace hg::habitat_assets;
    assert(available());
    for (size_t font = 0; font < FontCount; ++font) {
        assert(ascent(font) > 0 && line_height(font) >= ascent(font));
        for (unsigned int c = 0; c <= 255; ++c) {
            const auto* g = glyph(font, static_cast<unsigned char>(c));
            assert(g && g->width <= 128 && g->height <= 128);
            if (c < 32 || c > 126) assert(g == glyph(font, '?'));
        }
        assert(glyph(font, ' ')->advance > 0 && !glyph(font, ' ')->bits);
        assert(glyph(font, ':')->bits && glyph(font, ':')->y_offset < 0);
    }
    assert(glyph(Large, 'M')->height > glyph(Small, 'M')->height);
    assert(!glyph(FontCount, '?') && !glyph(static_cast<size_t>(-1), '?'));
    assert(ascent(FontCount) == 0 && line_height(FontCount) == 0);
    for (size_t resident = 0; resident < 8; ++resident) {
        for (size_t pose = 0; pose < 8; ++pose) {
            const auto* bitmap = frame(resident, pose);
            assert(bitmap && bitmap->width == 1 && bitmap->height == 1);
            const uint16_t expected = (((resident * 32 * 31 + 127) / 255) << 11)
                | (((pose * 32 * 63 + 127) / 255) << 5) | 31;
            assert(bitmap->pixels[0] == expected && bitmap->mask[0] == 0x80);
        }
    }
    assert(!frame(8, 0) && !frame(0, 8));
    assert(!frame(static_cast<size_t>(-1), static_cast<size_t>(-1)));
    for (size_t index = 0; index < 4; ++index) {
        const auto* bitmap = icon(index);
        assert(bitmap && bitmap->width == 1 && bitmap->height == 1);
        const uint16_t expected = 0xf800 | (((index * 32 * 63 + 127) / 255) << 5);
        assert(bitmap->pixels[0] == expected && bitmap->mask[0] == 0x80);
    }
    assert(!icon(4) && !icon(5) && !icon(static_cast<size_t>(-1)));
    for (size_t index = 0; index < 2; ++index) {
        const auto* overlay = layer(index);
        assert(overlay && overlay->x == 0 && overlay->y == (index == 0 ? 108 : 94));
        assert(overlay->bitmap.width == 384 && overlay->bitmap.height == (index == 0 ? 20 : 14));
        for (size_t i = 0; i < 384 * overlay->bitmap.height; ++i)
            assert(overlay->bitmap.pixels[i] == (index == 0 ? 0x001f : 0x07e0));
        for (size_t i = 0; i < 48 * overlay->bitmap.height; ++i)
            assert(overlay->bitmap.mask[i] == 0xff);
    }
    assert(!layer(2) && !layer(3) && !layer(static_cast<size_t>(-1)));
    const auto* scene = background();
    assert(scene && scene->width == 384 && scene->height == 128 && !scene->mask);
    for (size_t i = 0; i < 384 * 128; ++i) assert(scene->pixels[i] == 0xf800);
}
""", encoding="ascii")
    executable = tmp_path / "check"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(tmp_path), str(out), str(main), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
