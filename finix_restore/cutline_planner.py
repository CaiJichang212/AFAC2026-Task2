from __future__ import annotations

from dataclasses import dataclass

from finix_restore.chunk_geometry import nearest_band_center


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
    ) -> LongCutlineChoice:
        if cy1 <= y0:
            return LongCutlineChoice(y1=y0, source="fixed_cut")

        bounded_target = max(y0 + 1, min(target_y, cy1))
        if bounded_target >= cy1:
            return LongCutlineChoice(y1=cy1, source="fixed_cut")

        adjusted, source = nearest_band_center(bounded_target, bands, search_px)
        if source == "blank_band" and adjusted > y0:
            y1 = min(cy1, max(y0 + 1, adjusted))
            return LongCutlineChoice(y1=y1, source="blank_band")
        return LongCutlineChoice(y1=bounded_target, source="fixed_cut")
