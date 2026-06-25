from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageStat

from finix_restore.chunk_config import ChunkConfig
from finix_restore.long_layout import LongBlankBandDetector
from finix_restore.models import LayoutHints


def map_band_to_original(band: tuple[int, int], scale: float, limit: int) -> tuple[int, int]:
    start = max(0, min(limit, int(round(band[0] * scale))))
    end = max(start, min(limit, int(round(band[1] * scale))))
    return start, end


def _bands_from_projection(projection: np.ndarray, threshold: float, min_len: int) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for i, value in enumerate(projection):
        if value <= threshold:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                bands.append((start, i))
            start = None
    if start is not None and len(projection) - start >= min_len:
        bands.append((start, len(projection)))
    return bands


class LayoutSentry:
    def __init__(
        self,
        max_thumb_size: int = 1200,
        long_detector: LongBlankBandDetector | None = None,
    ) -> None:
        self.max_thumb_size = max_thumb_size
        self.long_detector = long_detector or LongBlankBandDetector()

    def analyze(self, image_path: Path, chunk_config: ChunkConfig | None = None) -> LayoutHints:
        chunk_config = chunk_config or ChunkConfig()
        with Image.open(image_path) as img:
            width, height = img.size
        if _is_long_strip_shape(width, height):
            detection = self.long_detector.detect(image_path, chunk_config.long)
            return LayoutHints(
                crop_box=detection.crop_box,
                horizontal_blank_bands=detection.horizontal_blank_bands,
                vertical_blank_bands=[],
                table_line_density=0.0,
                column_count=1,
            )

        with Image.open(image_path) as img:
            gray = img.convert("L")
            if max(width, height) > self.max_thumb_size:
                scale = self.max_thumb_size / max(width, height)
                thumb_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                gray = gray.resize(thumb_size)
            else:
                scale = 1.0
        stat = ImageStat.Stat(gray)
        if stat.stddev[0] < 2.0:
            return LayoutHints((0, 0, width, height), [], [], 0.0, 1)

        arr = np.asarray(gray, dtype=np.uint8)
        ink = arr < 245
        row_density = ink.mean(axis=1)
        col_density = ink.mean(axis=0)
        h_bands_thumb = _bands_from_projection(row_density, threshold=0.01, min_len=max(3, arr.shape[0] // 100))
        v_bands_thumb = _bands_from_projection(col_density, threshold=0.01, min_len=max(3, arr.shape[1] // 100))
        inv_scale = 1.0 / scale
        h_bands = [map_band_to_original(b, inv_scale, height) for b in h_bands_thumb]
        v_bands = [map_band_to_original(b, inv_scale, width) for b in v_bands_thumb]

        nonwhite = np.argwhere(ink)
        if nonwhite.size:
            y0, x0 = nonwhite.min(axis=0)
            y1, x1 = nonwhite.max(axis=0) + 1
            crop_box = (
                int(max(0, x0 * inv_scale)),
                int(max(0, y0 * inv_scale)),
                int(min(width, x1 * inv_scale)),
                int(min(height, y1 * inv_scale)),
            )
        else:
            crop_box = (0, 0, width, height)

        dense_cols = col_density > max(0.03, float(col_density.mean() * 1.5))
        column_count = 2 if len(v_bands) >= 1 and dense_cols.mean() > 0.05 else 1
        line_density = float((row_density > 0.35).mean() + (col_density > 0.35).mean()) / 2.0
        return LayoutHints(crop_box, h_bands, v_bands, line_density, column_count)


def _is_long_strip_shape(width: int, height: int) -> bool:
    return height >= 30_000 or (height / max(1, width)) >= 10
