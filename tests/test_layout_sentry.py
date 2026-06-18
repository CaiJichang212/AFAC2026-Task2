from PIL import Image, ImageDraw

from finix_restore.layout_sentry import LayoutSentry, map_band_to_original


def test_thumbnail_band_mapping_stays_in_original_bounds():
    assert map_band_to_original((10, 20), scale=4.0, limit=100) == (40, 80)
    assert map_band_to_original((20, 40), scale=3.0, limit=100) == (60, 100)


def test_layout_sentry_detects_horizontal_blank_band(tmp_path):
    image_path = tmp_path / "page.png"
    img = Image.new("L", (300, 500), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 280, 180), fill=0)
    draw.rectangle((20, 320, 280, 480), fill=0)
    img.convert("RGB").save(image_path)

    hints = LayoutSentry(max_thumb_size=500).analyze(image_path)

    assert hints.crop_box == (20, 20, 281, 481)
    assert any(start <= 250 <= end for start, end in hints.horizontal_blank_bands)


def test_layout_sentry_returns_empty_hints_for_low_contrast(tmp_path):
    image_path = tmp_path / "blank.png"
    Image.new("RGB", (300, 500), (250, 250, 250)).save(image_path)

    hints = LayoutSentry(max_thumb_size=200).analyze(image_path)

    assert hints.horizontal_blank_bands == []
    assert hints.vertical_blank_bands == []
    assert hints.column_count == 1
