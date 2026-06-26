from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LongCutlineChoice:
    y1: int
    source: str


class LongCutlinePlanner:
    def choose_cut(
        self,
        target_y: int,
        y0: int,
        cy1: int,
        bands: list[tuple[int, int]],
        search_px: int,
        min_quality_height_px: int = 0,
        quality_search_px: int = 0,
    ) -> LongCutlineChoice:
        if cy1 <= y0:
            return LongCutlineChoice(y1=y0, source="fixed_cut")

        bounded_target = max(y0 + 1, min(target_y, cy1))
        if bounded_target >= cy1:
            return LongCutlineChoice(y1=cy1, source="fixed_cut")

        effective_quality_search = quality_search_px if quality_search_px > 0 else search_px
        adjusted, source = self._nearest_band_center(
            bounded_target,
            bands,
            search_px,
            min_quality_height_px=min_quality_height_px,
            quality_search_px=effective_quality_search,
            y0=y0,
        )
        if source == "blank_band" and adjusted > y0:
            y1 = min(cy1, max(y0 + 1, adjusted))
            return LongCutlineChoice(y1=y1, source="blank_band")
        return LongCutlineChoice(y1=bounded_target, source="fixed_cut")

    @staticmethod
    def _nearest_band_center(
        target: int,
        bands: list[tuple[int, int]],
        search_px: int,
        *,
        min_quality_height_px: int = 0,
        quality_search_px: int = 0,
        y0: int = 0,
    ) -> tuple[int, str]:
        candidates: list[tuple[int, int, int]] = []
        for b0, b1 in bands:
            center = (b0 + b1) // 2
            if center <= y0:
                continue
            distance = abs(center - target)
            if distance <= max(search_px, quality_search_px):
                candidates.append((distance, b1 - b0, center))
        if not candidates:
            return target, "fixed_cut"
        if min_quality_height_px > 0:
            quality = [
                c for c in candidates
                if c[1] >= min_quality_height_px and c[0] <= (quality_search_px or search_px)
            ]
            if quality:
                quality.sort(key=lambda item: (item[0], -item[1]))
                return quality[0][2], "blank_band"
        nearby = [c for c in candidates if c[0] <= search_px]
        if not nearby:
            return target, "fixed_cut"
        nearby.sort(key=lambda item: item[0])
        return nearby[0][2], "blank_band"
