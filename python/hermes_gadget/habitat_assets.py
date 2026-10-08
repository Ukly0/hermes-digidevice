"""Convert private habitat PNGs and a UI font into a local C++ translation unit.

Requires Pillow (the images extra). Run with explicit input and output paths::

    python -m hermes_gadget.habitat_assets --assets /private/assets --out /tmp/habitat.cpp

Do not publish generated artwork or include it in repository/release packages.
Resident order is agumon, gabumon, biyomon, tentomon, palmon, gomamon,
patamon, gatomon; pose order is idleA, idleB, rest, attention, walkA, walkB,
moveA, moveB (0, 1, 7, 6, 2, 3, 4, 5). Frames must be 64x64 PNGs and each
resident's eight poses share one crop: the union of their nonzero-alpha bounds,
preserving source registration without resizing or compositing.
RGB565 channels are rounded to their nearest value.
Masks use alpha >= 128, MSB first, with each row padded to whole bytes.
The beach-island background must be an opaque 384x128 PNG and is not cropped.
Icons in icons/source are PNGs with canvases at most 64x64, independently
cropped to nonzero-alpha bounds. Icon order is NEW (7_0_0), question (16_0_0),
incident (17_0_0), notice (17_1_0). Each needs at least one alpha >= 128 pixel.
Required beach-island layers are 384x128 PNGs: layer_water.png is cropped to
(0, 108, 384, 128), layer_sand_sea.png to (0, 94, 384, 108). Each selected
band needs alpha >= 128 pixels. Shoreline masks additionally exclude RGB
identical to the base, before RGB565 conversion; an all-zero difference mask
is valid. Layer order is Water, Shoreline, with original crop origins.
The required fonts/pixel-digivolve/Pixel Digivolve.otf is rasterized by host
Pillow/FreeType at nominal 18px (Small) and 32px (Large), ASCII 32..126.
Glyph offsets are baseline-relative; draw at pen+x_offset, top+ascent+y_offset.
Glyph masks use coverage >= 128, MSB first, with byte-padded rows. No runtime
font engine or source font bytes are included in the generated translation unit.
generate() returns resident/frame/background/icon/layer/font/glyph counts and
rgb565_bytes, mask_bytes, font_bytes and total_bytes (array payload only,
excluding Bitmap/Layer/Glyph and font metrics metadata).
All inputs are validated before the output is atomically replaced.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


RESIDENTS = (
    ("agumon", 248), ("gabumon", 282), ("biyomon", 316), ("tentomon", 338),
    ("palmon", 360), ("gomamon", 382), ("patamon", 404), ("gatomon", 428),
)
OFFSETS = (0, 1, 7, 6, 2, 3, 4, 5)
ICONS = ("7_0_0.png", "16_0_0.png", "17_0_0.png", "17_1_0.png")
LAYERS = (("layer_water.png", (0, 108, 384, 128)),
          ("layer_sand_sea.png", (0, 94, 384, 108)))
FONT = Path("fonts/pixel-digivolve/Pixel Digivolve.otf")


def _fonts(path: Path) -> list[tuple[int, int, list[tuple[int, int, int, int, int, bytes]]]]:
    from PIL import Image, ImageDraw, ImageFont

    fonts = []
    try:
        for size in (18, 32):
            font = ImageFont.truetype(str(path), size=size)
            ascent, descent = font.getmetrics()
            if not 0 < ascent <= 65535 or not 0 < ascent + descent <= 65535:
                raise ValueError("font metrics outside uint16 bounds")
            glyphs = []
            for code in range(32, 127):
                character = chr(code)
                left, top, right, bottom = font.getbbox(character, anchor="ls")
                width, height = right - left, bottom - top
                advance = round(font.getlength(character))
                if not (0 <= width <= 128 and 0 <= height <= 128
                        and 0 <= advance <= 65535
                        and -32768 <= left <= 32767 and -32768 <= top <= 32767):
                    raise ValueError(f"glyph {code}: dimensions or metrics outside bounds")
                mask = bytearray()
                if width and height:
                    image = Image.new("L", (width, height))
                    ImageDraw.Draw(image).text((-left, -top), character, font=font,
                                               fill=255, anchor="ls")
                    stride = (width + 7) // 8
                    mask = bytearray(stride * height)
                    pixels = image.load()
                    for y in range(height):
                        for x in range(width):
                            if pixels[x, y] >= 128:
                                mask[y * stride + x // 8] |= 0x80 >> (x % 8)
                glyphs.append((width, height, advance, left, top, bytes(mask)))
            fonts.append((ascent, ascent + descent, glyphs))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return fonts


def _bitmaps(paths: list[Path], background: bool = False,
             icon: bool = False, band: tuple[int, int, int, int] | None = None,
             base: Path | None = None) -> list[tuple[int, int, list[int], bytes]]:
    from PIL import Image

    images, bounds = [], []
    for path in paths:
        try:
            with Image.open(path) as source:
                expected = (384, 128) if background or band else (64, 64)
                if icon:
                    if source.format != "PNG" or not all(0 < side <= 64 for side in source.size):
                        raise ValueError("expected PNG canvas between 1x1 and 64x64")
                elif source.format != "PNG" or source.size != expected:
                    raise ValueError(f"expected {expected[0]}x{expected[1]} PNG")
                image = source.convert("RGBA")
            if band:
                image = image.crop(band)
            alpha = image.getchannel("A")
            if background:
                if alpha.getextrema() != (255, 255):
                    raise ValueError("background must be fully opaque")
            else:
                box = alpha.getbbox()
                if box is None or alpha.getextrema()[1] < 128:
                    raise ValueError("empty frame (no alpha >= 128 pixels)")
                bounds.append(box)
            images.append(image)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: {exc}") from exc

    if icon:
        images = [image.crop(box) for image, box in zip(images, bounds)]
    elif not background and not band:
        common = (min(box[0] for box in bounds), min(box[1] for box in bounds),
                  max(box[2] for box in bounds), max(box[3] for box in bounds))
        images = [image.crop(common) for image in images]
    bitmaps = []
    base_colors = None
    if base is not None:
        with Image.open(base) as source:
            base_colors = source.convert("RGBA").crop(band).load()
    for image in images:
        width, height = image.size
        pixels = []
        mask = bytearray(((width + 7) // 8) * height) if not background else bytearray()
        colors = image.load()
        for y in range(height):
            for x in range(width):
                red, green, blue, opacity = colors[x, y]
                pixels.append(((red * 31 + 127) // 255 << 11)
                              | ((green * 63 + 127) // 255 << 5)
                              | ((blue * 31 + 127) // 255))
                if (mask and opacity >= 128
                        and (base_colors is None or (red, green, blue) != base_colors[x, y][:3])):
                    mask[y * ((width + 7) // 8) + x // 8] |= 0x80 >> (x % 8)
        bitmaps.append((width, height, pixels, bytes(mask)))
    return bitmaps


def generate(assets: Path, out: Path) -> dict:
    """Validate assets, write the hg::habitat_assets implementation, return budgets.

    Invalid/missing artwork or fonts raise ValueError without touching any existing
    output. Output must be outside the input tree to keep source assets intact.
    """
    assets, out = Path(assets), Path(out)
    if out.resolve().is_relative_to(assets.resolve()):
        raise ValueError("output must be outside the input assets directory")

    bitmaps = []
    for name, base in RESIDENTS:
        bitmaps.extend(_bitmaps([
            assets / name / "source" / f"{base + offset}_0_0.png" for offset in OFFSETS
        ]))
    bitmaps.extend(_bitmaps([assets / "environments" / "beach-island" / "layer_base.png"], True))
    for filename in ICONS:
        bitmaps.extend(_bitmaps([assets / "icons" / "source" / filename], icon=True))
    environment = assets / "environments" / "beach-island"
    for index, (filename, band) in enumerate(LAYERS):
        bitmaps.extend(_bitmaps([environment / filename], band=band,
                                base=environment / "layer_base.png" if index == 1 else None))
    fonts = _fonts(assets / FONT)
    lines = [
        "// Generated from private user-supplied artwork. Do not redistribute.",
        '#include "hg/habitat_assets.hpp"',
        "", "namespace hg::habitat_assets {", "namespace {",
    ]
    rgb565_bytes = mask_bytes = 0
    for index, (_, _, pixels, mask) in enumerate(bitmaps):
        for suffix, ctype, values, digits in (
            ("pixels", "uint16_t", pixels, 4), ("mask", "uint8_t", mask, 2),
        ):
            if not values:
                continue
            lines.append(f"static constexpr {ctype} k{index}_{suffix}[] = {{")
            for start in range(0, len(values), 12):
                lines.append("    " + ", ".join(
                    f"0x{value:0{digits}x}" for value in values[start:start + 12]
                ) + ",")
            lines.append("};")
        rgb565_bytes += len(pixels) * 2
        mask_bytes += len(mask)
    lines.append("static constexpr Bitmap kFrames[8][8] = {")
    for resident in range(8):
        lines.append("    {")
        for pose in range(8):
            index = resident * 8 + pose
            width, height, _, _ = bitmaps[index]
            lines.append(f"        {{{width}, {height}, k{index}_pixels, k{index}_mask}},")
        lines.append("    },")
    lines.extend([
        "};", "static constexpr Bitmap kBackground = {384, 128, k64_pixels, nullptr};",
        "static constexpr Bitmap kIcons[4] = {",
    ])
    for index in range(65, 69):
        width, height, _, _ = bitmaps[index]
        lines.append(f"    {{{width}, {height}, k{index}_pixels, k{index}_mask}},")
    lines.extend(["};", "static constexpr Layer kLayers[2] = {"])
    for index, (_, band) in enumerate(LAYERS, start=69):
        width, height, _, _ = bitmaps[index]
        lines.append(f"    {{{{{width}, {height}, k{index}_pixels, k{index}_mask}}, "
                     f"{band[0]}, {band[1]}}},")
    lines.append("};")
    font_bytes = 0
    for font_index, (_, _, glyphs) in enumerate(fonts):
        for code, (_, _, _, _, _, bits) in enumerate(glyphs, start=32):
            if bits:
                lines.append(f"static constexpr uint8_t kFont{font_index}_{code}[] = {{")
                for start in range(0, len(bits), 12):
                    lines.append("    " + ", ".join(
                        f"0x{value:02x}" for value in bits[start:start + 12]) + ",")
                lines.append("};")
                font_bytes += len(bits)
        lines.append(f"static constexpr Glyph kFont{font_index}[95] = {{")
        for code, (width, height, advance, x, y, bits) in enumerate(glyphs, start=32):
            pointer = f"kFont{font_index}_{code}" if bits else "nullptr"
            lines.append(f"    {{{width}, {height}, {advance}, {x}, {y}, {pointer}}},")
        lines.append("};")
    lines.extend([
        "static constexpr const Glyph* kFonts[2] = {kFont0, kFont1};",
        f"static constexpr uint16_t kAscents[2] = {{{fonts[0][0]}, {fonts[1][0]}}};",
        f"static constexpr uint16_t kLineHeights[2] = {{{fonts[0][1]}, {fonts[1][1]}}};",
        "} // namespace", "",
        "const Glyph* glyph(size_t font, unsigned char character) {",
        "    if (font >= 2) return nullptr;",
        "    if (character < 32 || character > 126) character = '?';",
        "    return &kFonts[font][character - 32];",
        "}",
        "uint16_t ascent(size_t font) { return font < 2 ? kAscents[font] : 0; }",
        "uint16_t line_height(size_t font) { return font < 2 ? kLineHeights[font] : 0; }",
        "const Bitmap* frame(size_t resident, size_t pose) {",
        "    return resident < 8 && pose < 8 ? &kFrames[resident][pose] : nullptr;",
        "}", "const Bitmap* background() { return &kBackground; }",
        "const Bitmap* icon(size_t index) { return index < 4 ? &kIcons[index] : nullptr; }",
        "const Layer* layer(size_t index) { return index < 2 ? &kLayers[index] : nullptr; }",
        "bool available() { return true; }", "} // namespace hg::habitat_assets", "",
    ])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", newline="\n",
                                         dir=out.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write("\n".join(lines))
        os.replace(temporary, out)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "residents": 8, "frames": 64, "backgrounds": 1, "icons": 4, "layers": 2,
        "fonts": 2, "glyphs": 190, "font_bytes": font_bytes,
        "rgb565_bytes": rgb565_bytes, "mask_bytes": mask_bytes,
        "total_bytes": rgb565_bytes + mask_bytes + font_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.assets, args.out)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, f"habitat-assets: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
