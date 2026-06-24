from __future__ import annotations

import math
from dataclasses import dataclass

from finix_restore.chunk_config import ChunkConfig
from finix_restore.chunk_geometry import box_pixels, expand_box
from finix_restore.models import ImageProfile, LayoutHints


@dataclass(frozen=True)
class TableImageVariant:
    kind: str
    source_bbox: tuple[int, int, int, int]
    sent_width: int
    sent_height: int
    scale: float
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class TableImagePlan:
    content_box: tuple[int, int, int, int]
    reference: TableImageVariant | None
    crop_mode: str
    warnings: tuple[str, ...]


class TableImagePolicy:
    def plan(self, profile: ImageProfile, hints: LayoutHints, config: ChunkConfig) -> TableImagePlan:
        full_box = (0, 0, profile.width, profile.height)
        crop_box = hints.crop_box or full_box
        expanded_box = expand_box(crop_box, config.crop_margin_px, profile.width, profile.height)
        coverage = box_pixels(expanded_box) / max(1, profile.pixels)

        warnings: list[str] = []
        if coverage < config.table.min_crop_coverage:
            content_box = full_box
            crop_mode = "full_image_fallback"
            warnings.append("low_crop_coverage")
        else:
            content_box = expanded_box
            crop_mode = "content_crop"

        reference = self._build_reference(profile, config)
        return TableImagePlan(
            content_box=content_box,
            reference=reference,
            crop_mode=crop_mode,
            warnings=tuple(warnings),
        )

    def _build_reference(self, profile: ImageProfile, config: ChunkConfig) -> TableImageVariant:
        scale = self._fit_scale(profile.width, profile.height, config.table.full_page_reference_max_pixels)
        sent_width = max(1, int(profile.width * scale))
        sent_height = max(1, int(profile.height * scale))
        risk_flags: list[str] = []
        if scale < 1.0:
            risk_flags.append("downscaled_reference")
        return TableImageVariant(
            kind="full_page_reference",
            source_bbox=(0, 0, profile.width, profile.height),
            sent_width=sent_width,
            sent_height=sent_height,
            scale=scale,
            risk_flags=tuple(risk_flags),
        )

    @staticmethod
    def _fit_scale(width: int, height: int, max_pixels: int) -> float:
        pixels = max(1, width * height)
        if pixels <= max_pixels:
            return 1.0
        return math.sqrt(max_pixels / pixels)
