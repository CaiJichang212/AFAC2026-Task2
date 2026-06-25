from importlib import import_module

import pytest
from PIL import Image, ImageDraw

from finix_restore.chunk_config import LongChunkConfig


def test_long_blank_detector_preserves_horizontal_bands_on_extreme_aspect(tmp_path):
    image_path = tmp_path / "long.png"
    img = Image.new("L", (300, 6000), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 0, 280, 2399), fill=0)
    draw.rectangle((20, 3600, 280, 5999), fill=0)
    img.convert("RGB").save(image_path)

    try:
        long_layout = import_module("finix_restore.long_layout")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing finix_restore.long_layout: {exc}")

    detector = long_layout.LongBlankBandDetector()
    detection = detector.detect(
        image_path,
        LongChunkConfig(
            blank_band_thumb_width=256,
            blank_band_max_thumb_height=40_000,
            blank_band_density_threshold=0.006,
            blank_band_min_height_px=50,
        ),
    )

    assert detection.thumb_size[0] == 256
    assert any(start <= 3000 <= end for start, end in detection.horizontal_blank_bands)
