from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageStat

from finix_restore.chunk_config import LongChunkConfig


def _map_band_to_original(band: tuple[int, int], inv_scale: float, limit: int) -> tuple[int, int]:
    start = max(0, min(limit, int(round(band[0] * inv_scale))))
    end = max(start, min(limit, int(round(band[1] * inv_scale))))
    return start, end


def _bands_from_projection(projection: np.ndarray, threshold: float, min_len: int) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(projection):
        if value <= threshold:
            if start is None:
                start = index
            continue
        if start is not None and index - start >= min_len:
            bands.append((start, index))
        start = None
    if start is not None and len(projection) - start >= min_len:
        bands.append((start, len(projection)))
    return bands


@dataclass(frozen=True)
class LongBlankBandDetection:
    crop_box: tuple[int, int, int, int]
    horizontal_blank_bands: list[tuple[int, int]]
    scale: float
    thumb_size: tuple[int, int]


class LongBlankBandDetector:
    def detect(self, image_path: Path, config: LongChunkConfig) -> LongBlankBandDetection:
        with Image.open(image_path) as img:
            width, height = img.size
            gray = img.convert("L")
            scale = min(
                config.blank_band_thumb_width / max(1, width),
                config.blank_band_max_thumb_height / max(1, height),
                1.0,
            )
            if scale < 1.0:
                thumb_size = (
                    max(1, int(round(width * scale))),
                    max(1, int(round(height * scale))),
                )
                gray = gray.resize(thumb_size)
            else:
                thumb_size = (width, height)

        stat = ImageStat.Stat(gray)
        if stat.stddev[0] < 2.0:
            return LongBlankBandDetection(
                crop_box=(0, 0, width, height),
                horizontal_blank_bands=[],
                scale=scale,
                thumb_size=thumb_size,
            )

        arr = np.asarray(gray, dtype=np.uint8)
        ink = arr < 245
        row_density = ink.mean(axis=1)
        inv_scale = 1.0 / scale if scale > 0 else 1.0
        min_len = max(1, int(math.ceil(config.blank_band_min_height_px * scale)))
        bands_thumb = _bands_from_projection(
            row_density,
            threshold=config.blank_band_density_threshold,
            min_len=min_len,
        )
        bands = [
            _map_band_to_original(band, inv_scale, height)
            for band in bands_thumb
        ]
        bands = [
            band for band in bands
            if band[1] - band[0] >= config.blank_band_min_height_px
        ]

        nonwhite = np.argwhere(ink)
        if nonwhite.size:
            y0, x0 = nonwhite.min(axis=0)
            y1, x1 = nonwhite.max(axis=0) + 1
            crop_box = (
                max(0, min(width, int(round(x0 * inv_scale)))),
                max(0, min(height, int(round(y0 * inv_scale)))),
                max(0, min(width, int(round(x1 * inv_scale)))),
                max(0, min(height, int(round(y1 * inv_scale)))),
            )
        else:
            crop_box = (0, 0, width, height)

        return LongBlankBandDetection(
            crop_box=crop_box,
            horizontal_blank_bands=bands,
            scale=scale,
            thumb_size=thumb_size,
        )
