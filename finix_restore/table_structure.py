from __future__ import annotations

import math
from dataclasses import dataclass

from finix_restore.chunk_config import ChunkConfig
from finix_restore.chunk_geometry import expand_box, nearest_band_center
from finix_restore.models import ImageProfile, LayoutHints


@dataclass(frozen=True)
class TablePlanEntry:
    base_bbox: tuple[int, int, int, int]
    crop_bbox: tuple[int, int, int, int]
    row_band: int
    col_band: int
    rows: int
    cols: int
    cut_source: str
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class TablePlan:
    content_box: tuple[int, int, int, int]
    entries: tuple[TablePlanEntry, ...]
    policy: str


class TableStructurePlanner:
    def plan(self, profile: ImageProfile, hints: LayoutHints, config: ChunkConfig) -> TablePlan:
        table_cfg = config.table
        content_box = self._resolve_content_box(profile, hints, config)
        cx0, cy0, cx1, cy1 = content_box
        content_width = max(1, cx1 - cx0)
        content_height = max(1, cy1 - cy0)
        content_pixels = content_width * content_height

        if content_pixels <= table_cfg.full_page_max_pixels:
            return TablePlan(
                content_box=content_box,
                entries=(
                    TablePlanEntry(
                        base_bbox=content_box,
                        crop_bbox=content_box,
                        row_band=0,
                        col_band=0,
                        rows=1,
                        cols=1,
                        cut_source="full_page",
                        risk_flags=(),
                    ),
                ),
                policy="table_structure_v1",
            )

        rows, cols = self._estimate_grid_shape(
            width=content_width,
            height=content_height,
            target_pixels=max(1, table_cfg.target_pixels),
            safe_max_pixels=max(1, table_cfg.safe_max_pixels),
            hard_max_pixels=max(1, config.hard_max_pixels),
            overlap_x=table_cfg.horizontal_overlap,
            overlap_y=table_cfg.vertical_overlap,
        )

        base_x_cuts = [cx0 + (i * content_width) // cols for i in range(cols)] + [cx1]
        base_y_cuts = [cy0 + (i * content_height) // rows for i in range(rows)] + [cy1]

        x_cuts, x_from_band = self._adjust_cuts(
            base_x_cuts,
            hints.vertical_blank_bands,
            table_cfg.cut_search_px,
        )
        y_cuts, y_from_band = self._adjust_cuts(
            base_y_cuts,
            hints.horizontal_blank_bands,
            table_cfg.cut_search_px,
        )

        x_cuts, x_from_band, y_cuts, y_from_band = self._enforce_pixel_budget(
            base_x_cuts=base_x_cuts,
            base_y_cuts=base_y_cuts,
            x_cuts=x_cuts,
            x_from_band=x_from_band,
            y_cuts=y_cuts,
            y_from_band=y_from_band,
            content_box=content_box,
            overlap_x=table_cfg.horizontal_overlap,
            overlap_y=table_cfg.vertical_overlap,
            safe_max_pixels=table_cfg.safe_max_pixels,
        )

        entries: list[TablePlanEntry] = []
        for row in range(rows):
            base_y0 = y_cuts[row]
            base_y1 = y_cuts[row + 1]
            top_band = y_from_band[row]
            bottom_band = y_from_band[row + 1]
            for col in range(cols):
                base_x0 = x_cuts[col]
                base_x1 = x_cuts[col + 1]
                left_band = x_from_band[col]
                right_band = x_from_band[col + 1]

                x0 = max(cx0, base_x0 - (table_cfg.horizontal_overlap if col > 0 else 0))
                x1 = min(cx1, base_x1 + (table_cfg.horizontal_overlap if col < cols - 1 else 0))
                y0 = max(cy0, base_y0 - (table_cfg.vertical_overlap if row > 0 else 0))
                y1 = min(cy1, base_y1 + (table_cfg.vertical_overlap if row < rows - 1 else 0))
                if x1 <= x0:
                    x1 = min(cx1, x0 + 1)
                if y1 <= y0:
                    y1 = min(cy1, y0 + 1)

                cell_uses_band = any(
                    (
                        col > 0 and left_band,
                        col < cols - 1 and right_band,
                        row > 0 and top_band,
                        row < rows - 1 and bottom_band,
                    )
                )
                cut_source = "blank_band" if cell_uses_band else "fixed_cut"
                risk_flags = ("fixed_cut",) if cut_source == "fixed_cut" and (rows > 1 or cols > 1) else ()

                entries.append(
                    TablePlanEntry(
                        base_bbox=(base_x0, base_y0, base_x1, base_y1),
                        crop_bbox=(x0, y0, x1, y1),
                        row_band=row,
                        col_band=col,
                        rows=rows,
                        cols=cols,
                        cut_source=cut_source,
                        risk_flags=risk_flags,
                    )
                )

        return TablePlan(
            content_box=content_box,
            entries=tuple(entries),
            policy="table_structure_v1",
        )

    @staticmethod
    def _resolve_content_box(
        profile: ImageProfile,
        hints: LayoutHints,
        config: ChunkConfig,
    ) -> tuple[int, int, int, int]:
        crop = hints.crop_box if hints.crop_box else (0, 0, profile.width, profile.height)
        expanded = expand_box(crop, config.crop_margin_px, profile.width, profile.height)
        x0, y0, x1, y1 = expanded
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return (0, 0, profile.width, profile.height)
        return expanded

    @staticmethod
    def _estimate_grid_shape(
        width: int,
        height: int,
        target_pixels: int,
        safe_max_pixels: int,
        hard_max_pixels: int,
        overlap_x: int,
        overlap_y: int,
    ) -> tuple[int, int]:
        area = max(1, width * height)
        cols = max(1, math.ceil(math.sqrt(area / max(1, target_pixels))))
        rows = max(1, math.ceil(area / (cols * max(1, target_pixels))))

        def worst_chunk_pixels(rows_: int, cols_: int) -> int:
            base_w = math.ceil(width / cols_)
            base_h = math.ceil(height / rows_)
            extra_w = (2 * overlap_x) if cols_ > 2 else (overlap_x if cols_ > 1 else 0)
            extra_h = (2 * overlap_y) if rows_ > 2 else (overlap_y if rows_ > 1 else 0)
            return (base_w + extra_w) * (base_h + extra_h)

        max_iter = 50
        for _ in range(max_iter):
            if worst_chunk_pixels(rows, cols) <= safe_max_pixels:
                break
            base_w = math.ceil(width / cols)
            base_h = math.ceil(height / rows)
            if base_w >= base_h:
                cols += 1
            else:
                rows += 1

        for _ in range(max_iter):
            if worst_chunk_pixels(rows, cols) <= hard_max_pixels:
                break
            base_w = math.ceil(width / cols)
            base_h = math.ceil(height / rows)
            if base_w >= base_h:
                cols += 1
            else:
                rows += 1

        return rows, cols

    @staticmethod
    def _adjust_cuts(
        base_cuts: list[int],
        bands: list[tuple[int, int]],
        search_px: int,
    ) -> tuple[list[int], list[bool]]:
        if len(base_cuts) <= 2:
            return list(base_cuts), [False] * len(base_cuts)

        adjusted: list[int] = [base_cuts[0]]
        from_band: list[bool] = [False]
        for index in range(1, len(base_cuts) - 1):
            target = base_cuts[index]
            new_value, source = nearest_band_center(target, bands, search_px)
            prev = adjusted[-1]
            upper = base_cuts[index + 1]
            if source == "blank_band" and prev < new_value < upper:
                adjusted.append(new_value)
                from_band.append(True)
            else:
                adjusted.append(target)
                from_band.append(False)
        adjusted.append(base_cuts[-1])
        from_band.append(False)
        return adjusted, from_band

    @staticmethod
    def _enforce_pixel_budget(
        base_x_cuts: list[int],
        base_y_cuts: list[int],
        x_cuts: list[int],
        x_from_band: list[bool],
        y_cuts: list[int],
        y_from_band: list[bool],
        content_box: tuple[int, int, int, int],
        overlap_x: int,
        overlap_y: int,
        safe_max_pixels: int,
    ) -> tuple[list[int], list[bool], list[int], list[bool]]:
        x_cuts = list(x_cuts)
        x_from_band = list(x_from_band)
        y_cuts = list(y_cuts)
        y_from_band = list(y_from_band)

        cx0, cy0, cx1, cy1 = content_box
        rows = len(y_cuts) - 1
        cols = len(x_cuts) - 1
        max_iter = (cols + rows) * 4 + 8

        def cell_pixels(row: int, col: int) -> int:
            base_x0 = x_cuts[col]
            base_x1 = x_cuts[col + 1]
            base_y0 = y_cuts[row]
            base_y1 = y_cuts[row + 1]
            x0 = max(cx0, base_x0 - (overlap_x if col > 0 else 0))
            x1 = min(cx1, base_x1 + (overlap_x if col < cols - 1 else 0))
            y0 = max(cy0, base_y0 - (overlap_y if row > 0 else 0))
            y1 = min(cy1, base_y1 + (overlap_y if row < rows - 1 else 0))
            return max(0, x1 - x0) * max(0, y1 - y0)

        for _ in range(max_iter):
            offending: tuple[int, int, int] | None = None
            for row in range(rows):
                for col in range(cols):
                    pixels = cell_pixels(row, col)
                    if pixels > safe_max_pixels:
                        if offending is None or pixels > offending[0]:
                            offending = (pixels, row, col)
            if offending is None:
                break

            _, row, col = offending
            candidates: list[tuple[int, str, int]] = []
            for cut_idx in (col, col + 1):
                if 0 < cut_idx < len(x_cuts) - 1 and x_from_band[cut_idx]:
                    drift = abs(x_cuts[cut_idx] - base_x_cuts[cut_idx])
                    candidates.append((drift, "x", cut_idx))
            for cut_idx in (row, row + 1):
                if 0 < cut_idx < len(y_cuts) - 1 and y_from_band[cut_idx]:
                    drift = abs(y_cuts[cut_idx] - base_y_cuts[cut_idx])
                    candidates.append((drift, "y", cut_idx))
            if not candidates:
                break
            candidates.sort(key=lambda item: -item[0])
            _, axis, cut_idx = candidates[0]
            if axis == "x":
                x_cuts[cut_idx] = base_x_cuts[cut_idx]
                x_from_band[cut_idx] = False
            else:
                y_cuts[cut_idx] = base_y_cuts[cut_idx]
                y_from_band[cut_idx] = False

        return x_cuts, x_from_band, y_cuts, y_from_band
