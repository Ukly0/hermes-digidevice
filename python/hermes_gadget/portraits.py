"""Prepare externally supplied portrait frames as registered 1-bit masks.

This does not replace the shipped mascot or assign Hermes states to artwork.
Use an ignored output directory; third-party artwork must stay external.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw


SIZES = (64, 96, 144, 192)
INK = (227, 245, 234)
BACKGROUND = (13, 29, 36)


def compose_feature(base: Image.Image, frame: Image.Image,
                    replacement_mask: Image.Image) -> Image.Image:
    """Replace one explicit feature region, preserving every other RGBA pixel."""
    if base.size != frame.size or base.size != replacement_mask.size:
        raise ValueError("base, feature frame and mask must share a canvas")
    if replacement_mask.mode != "L" or not set(replacement_mask.tobytes()) <= {0, 255}:
        raise ValueError("replacement mask must be binary L (0 or 255)")
    return Image.composite(frame.convert("RGBA"), base.convert("RGBA"), replacement_mask)


def monochrome(source: Image.Image, threshold: int = 110) -> Image.Image:
    """Light regions become ink; dark facial features become negative space.

    Alpha alone would produce an unreadable silhouette. Transparent RGB must
    never contribute ink, regardless of its stored color.
    """
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255")
    rgba = source.convert("RGBA")
    luminance, alpha = rgba.convert("L"), rgba.getchannel("A")
    mask = Image.new("L", source.size)
    mask.frombytes(bytes(255 if light > threshold and opacity >= 128 else 0
                         for light, opacity in zip(luminance.tobytes(), alpha.tobytes())))
    if not mask.getbbox():
        raise ValueError("frame has no visible monochrome ink")
    return mask


def fit_mask(mask: Image.Image, size: int) -> Image.Image:
    """Fit the whole source canvas, never crop individual expressions."""
    if size not in SIZES:
        raise ValueError(f"size must be one of {SIZES}")
    scale = min(size / mask.width, size / mask.height)
    dimensions = (max(1, round(mask.width * scale)), max(1, round(mask.height * scale)))
    fitted = mask.resize(dimensions, Image.Resampling.LANCZOS)
    fitted = fitted.point(lambda value: 255 if value > 110 else 0)
    result = Image.new("L", (size, size))
    result.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return result


def pack_mask(mask: Image.Image) -> bytes:
    """Row-major MSB-first bits, each row padded to a whole byte."""
    stride = (mask.width + 7) // 8
    packed = bytearray(stride * mask.height)
    pixels = mask.load()
    for y in range(mask.height):
        for x in range(mask.width):
            if pixels[x, y] >= 128:
                packed[y * stride + x // 8] |= 0x80 >> (x % 8)
    return bytes(packed)


def tinted(mask: Image.Image) -> Image.Image:
    result = Image.new("RGBA", mask.size, (*INK, 255))
    result.putalpha(mask)
    return result


def prepare(paths: list[Path], output: Path, threshold: int = 110,
            sequence: list[str] | None = None) -> dict:
    if not paths:
        raise ValueError("no input PNG frames")
    names = [path.stem for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("frame names must be unique")
    if sequence is not None and (not sequence or any(name not in names for name in sequence)):
        raise ValueError("sequence must refer to existing frame stems")
    masks, canvas = {}, None
    for path in paths:
        with Image.open(path) as source:
            if source.format != "PNG":
                raise ValueError(f"{path.name}: expected PNG")
            if canvas is not None and source.size != canvas:
                raise ValueError("all frames must share the same source canvas")
            canvas = source.size
            masks[path.stem] = monochrome(source, threshold)
    if output.exists():
        raise ValueError("output directory already exists; choose a new directory")

    # Validate/encode every input before creating any output files.
    files: dict[str, bytes] = {}
    frames = []
    large = {}
    for name, mask in masks.items():
        variants = []
        for size in SIZES:
            fitted = fit_mask(mask, size)
            packed = pack_mask(fitted)
            stem = f"{name}-{size}"
            files[stem + ".bin"] = packed
            png = BytesIO()
            tinted(fitted).save(png, format="PNG")
            files[stem + ".png"] = png.getvalue()
            variants.append({"size": size, "bits": stem + ".bin", "png": stem + ".png",
                             "bytes": len(packed),
                             "ink_pixels": sum(byte.bit_count() for byte in packed)})
            if size == 192:
                large[name] = fitted
        frames.append({"name": name, "variants": variants})

    columns = min(6, len(names))
    rows = (len(names) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 208, rows * 224), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for index, name in enumerate(names):
        x, y = index % columns * 208, index // columns * 224
        sheet.paste(INK, (x + 8, y + 8), large[name])
        draw.text((x + 8, y + 205), name, fill=INK)
    png = BytesIO()
    sheet.save(png, format="PNG")
    files["contact-sheet.png"] = png.getvalue()
    if sequence is not None:
        animation = []
        for name in sequence:
            frame = Image.new("RGB", (208, 224), BACKGROUND)
            frame.paste(INK, (8, 8), large[name])
            ImageDraw.Draw(frame).text((8, 205), name, fill=INK)
            animation.append(frame)
        gif = BytesIO()
        animation[0].save(gif, format="GIF", save_all=True, append_images=animation[1:],
                          duration=250, loop=0, disposal=2)
        files["animation-preview.gif"] = gif.getvalue()
    report = {"format": "1bit-msb-first-row-padded", "source_canvas": canvas,
              "threshold": threshold, "ink_rgb": INK, "preview_background_rgb": BACKGROUND,
              "state_assignment": "not integrated", "frames": frames,
              "bitmap_bytes": sum(v["bytes"] for f in frames for v in f["variants"]),
              "preview_sequence": sequence}
    files["manifest.json"] = (json.dumps(report, indent=2) + "\n").encode()
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new external or ignored output directory")
    parser.add_argument("--threshold", type=int, default=110)
    parser.add_argument("--sequence", nargs="+", help="frame stems for a visual preview, not real states")
    args = parser.parse_args()
    try:
        report = prepare(args.inputs, args.out, args.threshold, args.sequence)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Prepared {len(report['frames'])} frames: {report['bitmap_bytes']} bitmap bytes")
    print(f"Preview: {args.out / 'contact-sheet.png'}")


if __name__ == "__main__":
    main()
