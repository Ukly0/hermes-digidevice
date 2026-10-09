"""Synthetic artwork only; no externally supplied character pixels."""

import json

import pytest

pytest.importorskip("PIL")
from PIL import Image

from hermes_gadget.portraits import compose_feature, fit_mask, monochrome, pack_mask, prepare


def test_feature_replacement_keeps_body_pixels_and_alpha_exact():
    base = Image.new("RGBA", (4, 4), (120, 90, 80, 255))
    base.putpixel((0, 0), (10, 20, 30, 0))
    frame = Image.new("RGBA", (4, 4), (230, 200, 100, 0))
    frame.putpixel((1, 1), (255, 100, 100, 255))
    mask = Image.new("L", (4, 4))
    mask.putpixel((1, 1), 255)
    mask.putpixel((2, 1), 255)
    result = compose_feature(base, frame, mask)
    for y in range(4):
        for x in range(4):
            assert result.getpixel((x, y)) == (frame if mask.getpixel((x, y)) else base).getpixel((x, y))
    assert result.getpixel((2, 1))[3] == 0  # Replacement can erase an old feature.
    assert base.getpixel((1, 1)) == (120, 90, 80, 255)


def test_feature_replacement_rejects_misaligned_or_soft_masks():
    base = Image.new("RGBA", (4, 4))
    with pytest.raises(ValueError, match="canvas"):
        compose_feature(base, Image.new("RGBA", (3, 4)), Image.new("L", (4, 4)))
    for mask in (Image.new("L", (4, 4), 128), Image.new("RGB", (4, 4))):
        with pytest.raises(ValueError, match="binary"):
            compose_feature(base, base, mask)


def test_monochrome_preserves_dark_features_and_ignores_transparent_rgb():
    image = Image.new("RGBA", (4, 1))
    image.putdata([(255, 255, 255, 0), (250, 240, 210, 255), (20, 20, 30, 255),
                   (255, 255, 255, 127)])
    assert monochrome(image).tobytes() == bytes([0, 255, 0, 0])


def test_alpha_alone_does_not_turn_color_art_into_a_silhouette():
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    assert monochrome(image).tobytes() == bytes([255, 0])


def test_row_padding_and_msb_first_match_core_contract():
    mask = Image.new("L", (9, 2))
    for point in ((0, 0), (7, 0), (8, 0), (1, 1)):
        mask.putpixel(point, 255)
    assert pack_mask(mask) == bytes([0x81, 0x80, 0x40, 0x00])


def test_registration_preserves_source_canvas_instead_of_individual_crop():
    a, b = Image.new("L", (128, 128)), Image.new("L", (128, 128))
    for image in (a, b):
        for y in range(20, 50):
            for x in range(20, 50):
                image.putpixel((x, y), 255)
    b.putpixel((100, 100), 255)
    assert fit_mask(a, 192).crop((0, 0, 90, 90)).tobytes() == fit_mask(b, 192).crop((0, 0, 90, 90)).tobytes()


def test_prepare_exports_binary_masks_sizes_and_visual_previews(tmp_path):
    paths = []
    for name in ("idle", "blink", "talk"):
        path = tmp_path / (name + ".png")
        image = Image.new("RGBA", (128, 128), (255, 255, 255, 255))
        image.putpixel((40, 40), (0, 0, 0, 255))
        image.save(path)
        paths.append(path)
    output = tmp_path / "prepared"
    report = prepare(paths, output, sequence=["idle", "blink", "talk"])
    assert report["bitmap_bytes"] == 26592
    assert json.loads((output / "manifest.json").read_text())["state_assignment"] == "not integrated"
    assert (output / "contact-sheet.png").is_file()
    with Image.open(output / "animation-preview.gif") as animation:
        assert animation.size == (208, 224)
    for frame in report["frames"]:
        for variant in frame["variants"]:
            size = variant["size"]
            assert len((output / variant["bits"]).read_bytes()) == size * ((size + 7) // 8)
            with Image.open(output / variant["png"]) as png:
                assert png.size == (size, size)
                assert set(png.getchannel("A").tobytes()) <= {0, 255}
    with pytest.raises(ValueError, match="already exists"):
        prepare(paths, output)


def test_invalid_input_does_not_create_output(tmp_path):
    paths = []
    for index, size in enumerate((128, 64)):
        path = tmp_path / f"{index}.png"
        Image.new("RGBA", (size, size), "white").save(path)
        paths.append(path)
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="same source canvas"):
        prepare(paths, output)
    assert not output.exists()
    with pytest.raises(ValueError, match="sequence"):
        prepare(paths, output, sequence=["missing"])
    with pytest.raises(ValueError, match="no input"):
        prepare([], output)


@pytest.mark.parametrize("threshold", [-1, 256])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError, match="threshold"):
        monochrome(Image.new("RGBA", (1, 1), "white"), threshold)


def test_empty_ink_is_rejected():
    with pytest.raises(ValueError, match="no visible"):
        monochrome(Image.new("RGBA", (8, 8), "black"))
