from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from finix_restore.chunk_config import ChunkConfig, LongChunkConfig, TableChunkConfig
from finix_restore.chunk_geometry import (
    box_pixels,
    expand_box,
    nearest_band_center,
    overlap_dict,
    traceable_chunk_name,
)
from finix_restore.models import Chunk, ImageProfile, LayoutHints


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _chunk_id(file_name: str, bbox: tuple[int, int, int, int], image_sha1: str) -> str:
    raw = f"{file_name}:{bbox}:{image_sha1}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _write_manifest(
    stem_dir: Path,
    profile: ImageProfile,
    chunks: list[Chunk],
    content_box: tuple[int, int, int, int],
    chunk_policy: str,
) -> None:
    payload = {
        "file_name": profile.file_name,
        "width": profile.width,
        "height": profile.height,
        "doc_type": profile.doc_type,
        "content_box": list(content_box),
        "chunk_policy": chunk_policy,
        "chunks": [
            {
                **asdict(chunk),
                "image_path": str(chunk.image_path),
                "bbox": list(chunk.bbox),
                "risk_flags": list(chunk.risk_flags),
            }
            for chunk in chunks
        ],
    }
    (stem_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_crop(source: Path, bbox: tuple[int, int, int, int], out_path: Path) -> None:
    if out_path.exists():
        return
    with Image.open(source) as img:
        img.crop(bbox).convert("RGB").save(out_path, format="JPEG", quality=95)


class LongStripChunker:
    def __init__(
        self,
        chunks_dir: Path,
        config: ChunkConfig | None = None,
        window_height: int = 4000,
        overlap: int = 320,
    ) -> None:
        self.chunks_dir = Path(chunks_dir)
        if config is None:
            config = ChunkConfig(
                long=LongChunkConfig(
                    max_window_height=window_height,
                    vertical_overlap=overlap,
                )
            )
        self.config = config
        self.long_cfg = config.long

    def chunk(self, profile: ImageProfile, hints: LayoutHints) -> list[Chunk]:
        stem_dir = self.chunks_dir / Path(profile.file_name).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        image_sha1 = _file_sha1(profile.path)

        content_box = self._resolve_content_box(profile, hints)
        cx0, cy0, cx1, cy1 = content_box
        content_width = max(1, cx1 - cx0)

        long_cfg = self.long_cfg
        target_h = max(1, long_cfg.target_pixels // content_width)
        safe_h = max(1, long_cfg.safe_max_pixels // content_width)
        window_h = min(
            long_cfg.max_window_height,
            max(long_cfg.min_window_height, target_h),
            safe_h,
        )
        window_h = max(1, window_h)
        v_overlap = long_cfg.vertical_overlap

        # First pass: pick (y0, y1, cut_source) tuples covering content vertically.
        slices: list[tuple[int, int, str]] = []
        y0 = cy0
        guard = 0
        while y0 < cy1:
            guard += 1
            if guard > 10000:
                raise RuntimeError("LongStripChunker exceeded slice iteration guard")
            target_y1 = min(cy1, y0 + window_h)
            is_last = target_y1 >= cy1
            if is_last:
                y1 = cy1
                cut_source = "dynamic_window"
            else:
                adjusted, source = nearest_band_center(
                    target_y1,
                    hints.horizontal_blank_bands,
                    long_cfg.blank_band_search_px,
                )
                if source == "blank_band" and adjusted > y0:
                    y1 = min(cy1, max(y0 + 1, adjusted))
                    cut_source = "blank_band"
                else:
                    y1 = target_y1
                    cut_source = "dynamic_window"
            if y1 <= y0:
                y1 = min(cy1, y0 + 1)
            slices.append((y0, y1, cut_source))
            if y1 >= cy1:
                break
            next_y0 = y1 - v_overlap if v_overlap else y1
            if next_y0 <= y0:
                next_y0 = y0 + 1
            y0 = next_y0

        rows = len(slices)
        chunks: list[Chunk] = []
        stem = Path(profile.file_name).stem
        for row, (y0, y1, cut_source) in enumerate(slices):
            is_last_row = row == rows - 1
            bbox = (cx0, y0, cx1, y1)
            cid = _chunk_id(profile.file_name, bbox, image_sha1)
            out_path = stem_dir / traceable_chunk_name(stem, row, 0, bbox)
            _save_crop(profile.path, bbox, out_path)

            ovl = overlap_dict(
                row=row,
                col=0,
                rows=rows,
                cols=1,
                horizontal=0,
                vertical=v_overlap,
            )

            chunk_pixels = box_pixels(bbox)
            flags: list[str] = []
            if chunk_pixels > long_cfg.safe_max_pixels:
                flags.append("over_safe_pixels")
            if chunk_pixels > self.config.hard_max_pixels:
                flags.append("over_hard_pixels")
            if not is_last_row and cut_source != "blank_band":
                flags.append("fixed_cut")
            if 0 < chunk_pixels < self.config.min_pixels:
                flags.append("small_tail")
            # de-duplicate while preserving order
            seen: set[str] = set()
            unique_flags: list[str] = []
            for f in flags:
                if f not in seen:
                    seen.add(f)
                    unique_flags.append(f)

            chunks.append(
                Chunk(
                    chunk_id=cid,
                    file_name=profile.file_name,
                    image_path=out_path,
                    bbox=bbox,
                    row=row,
                    col=0,
                    overlap=ovl,
                    image_sha1=image_sha1,
                    chunk_pixels=chunk_pixels,
                    is_last_row=is_last_row,
                    is_last_col=True,
                    cut_source=cut_source,
                    risk_flags=tuple(unique_flags),
                )
            )

        _write_manifest(
            stem_dir,
            profile,
            chunks,
            content_box=content_box,
            chunk_policy="long_dynamic_v1",
        )
        return chunks

    def _resolve_content_box(
        self,
        profile: ImageProfile,
        hints: LayoutHints,
    ) -> tuple[int, int, int, int]:
        crop = hints.crop_box if hints.crop_box else (0, 0, profile.width, profile.height)
        expanded = expand_box(crop, self.config.crop_margin_px, profile.width, profile.height)
        x0, y0, x1, y1 = expanded
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return (0, 0, profile.width, profile.height)
        return expanded


class TableGridChunker:
    def __init__(
        self,
        chunks_dir: Path,
        config: ChunkConfig | None = None,
        max_chunk_pixels: int = 12_000_000,
        full_page_max_pixels: int = 16_000_000,
        horizontal_overlap: int = 160,
        vertical_overlap: int = 220,
    ) -> None:
        self.chunks_dir = Path(chunks_dir)
        if config is None:
            config = ChunkConfig(
                table=TableChunkConfig(
                    target_pixels=max_chunk_pixels,
                    safe_max_pixels=max_chunk_pixels,
                    full_page_max_pixels=full_page_max_pixels,
                    horizontal_overlap=horizontal_overlap,
                    vertical_overlap=vertical_overlap,
                )
            )
        self.config = config
        self.table_cfg = config.table
        # Legacy attribute names retained for any caller that still reads them.
        self.max_chunk_pixels = self.table_cfg.target_pixels
        self.full_page_max_pixels = self.table_cfg.full_page_max_pixels
        self.horizontal_overlap = self.table_cfg.horizontal_overlap
        self.vertical_overlap = self.table_cfg.vertical_overlap

    def chunk(self, profile: ImageProfile, hints: LayoutHints) -> list[Chunk]:
        content_box = self._resolve_content_box(profile, hints)
        cx0, cy0, cx1, cy1 = content_box
        content_width = max(1, cx1 - cx0)
        content_height = max(1, cy1 - cy0)
        content_pixels = content_width * content_height

        table_cfg = self.table_cfg

        if content_pixels <= table_cfg.full_page_max_pixels:
            entries = [
                {
                    "bbox": content_box,
                    "base_bbox": content_box,
                    "overlap_bbox": content_box,
                    "row": 0,
                    "col": 0,
                    "rows": 1,
                    "cols": 1,
                    "cut_source": "full_page",
                    "table_group_id": Path(profile.file_name).stem,
                    "row_band": 0,
                    "col_band": 0,
                    "requires_row_assembly": False,
                    "horizontal_overlap": 0,
                    "vertical_overlap": 0,
                }
            ]
            return self._materialize(
                profile,
                content_box=content_box,
                entries=entries,
                chunk_policy="table_grid_v2",
                safe_max=table_cfg.safe_max_pixels,
            )

        overlap_x = table_cfg.horizontal_overlap
        overlap_y = table_cfg.vertical_overlap

        rows, cols = self._estimate_grid_shape(
            width=content_width,
            height=content_height,
            target_pixels=max(1, table_cfg.target_pixels),
            safe_max_pixels=max(1, table_cfg.safe_max_pixels),
            hard_max_pixels=max(1, self.config.hard_max_pixels),
            overlap_x=overlap_x,
            overlap_y=overlap_y,
        )

        # Build base grid cuts inside content_box (inclusive endpoints).
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

        # Re-check pixel budget after blank-band adjustment. Moving a cut to a
        # band can enlarge a neighbouring cell beyond safe_max once overlap is
        # added; if so, fall back the offending band-adjusted cut to its base
        # position and re-check until all cells fit (or no more band cuts to
        # rollback). Endpoints are never adjusted, so this loop terminates.
        x_cuts, x_from_band, y_cuts, y_from_band = self._enforce_pixel_budget(
            base_x_cuts=base_x_cuts,
            base_y_cuts=base_y_cuts,
            x_cuts=x_cuts,
            x_from_band=x_from_band,
            y_cuts=y_cuts,
            y_from_band=y_from_band,
            content_box=content_box,
            overlap_x=overlap_x,
            overlap_y=overlap_y,
            safe_max_pixels=table_cfg.safe_max_pixels,
        )

        entries: list[dict] = []
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

                x0 = max(cx0, base_x0 - (overlap_x if col > 0 else 0))
                x1 = min(cx1, base_x1 + (overlap_x if col < cols - 1 else 0))
                y0 = max(cy0, base_y0 - (overlap_y if row > 0 else 0))
                y1 = min(cy1, base_y1 + (overlap_y if row < rows - 1 else 0))
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
                cut_source = "blank_band" if cell_uses_band else "grid"

                entries.append(
                    {
                        "bbox": (x0, y0, x1, y1),
                        "base_bbox": (base_x0, base_y0, base_x1, base_y1),
                        "overlap_bbox": (x0, y0, x1, y1),
                        "row": row,
                        "col": col,
                        "rows": rows,
                        "cols": cols,
                        "cut_source": cut_source,
                        "table_group_id": Path(profile.file_name).stem,
                        "row_band": row,
                        "col_band": col,
                        "requires_row_assembly": rows > 1 or cols > 1,
                        "horizontal_overlap": overlap_x,
                        "vertical_overlap": overlap_y,
                    }
                )

        return self._materialize(
            profile,
            content_box=content_box,
            entries=entries,
            chunk_policy="table_grid_v2",
            safe_max=table_cfg.safe_max_pixels,
        )

    def _resolve_content_box(
        self,
        profile: ImageProfile,
        hints: LayoutHints,
    ) -> tuple[int, int, int, int]:
        crop = hints.crop_box if hints.crop_box else (0, 0, profile.width, profile.height)
        expanded = expand_box(crop, self.config.crop_margin_px, profile.width, profile.height)
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
            # Interior cells get overlap on both sides; use it as the worst case.
            extra_w = (2 * overlap_x) if cols_ > 2 else (overlap_x if cols_ > 1 else 0)
            extra_h = (2 * overlap_y) if rows_ > 2 else (overlap_y if rows_ > 1 else 0)
            max_w = base_w + extra_w
            max_h = base_h + extra_h
            return max_w * max_h

        max_iter = 50
        # First, ensure we are below safe_max_pixels.
        for _ in range(max_iter):
            if worst_chunk_pixels(rows, cols) <= safe_max_pixels:
                break
            base_w = math.ceil(width / cols)
            base_h = math.ceil(height / rows)
            if base_w >= base_h:
                cols += 1
            else:
                rows += 1

        # Then, ensure we are below hard_max_pixels (must succeed).
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
        # Endpoints stay fixed and are never marked as blank_band.
        if len(base_cuts) <= 2:
            return list(base_cuts), [False] * len(base_cuts)

        adjusted: list[int] = [base_cuts[0]]
        from_band: list[bool] = [False]
        for i in range(1, len(base_cuts) - 1):
            target = base_cuts[i]
            new_value, source = nearest_band_center(target, bands, search_px)
            prev = adjusted[-1]
            # Look ahead at the next fixed cut as an upper bound to keep monotonic.
            upper = base_cuts[i + 1]
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
        """Roll back blank-band cut adjustments that push any cell over safe_max.

        Iteratively rebuilds final overlap-included bboxes for every cell;
        whenever a cell exceeds ``safe_max_pixels`` it picks the most-shifted
        band-adjusted cut that touches the cell and resets it to the base grid
        position. Endpoints are never adjusted, so progress is monotonic and
        the loop terminates.
        """
        # Defensive copies so we can mutate.
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
            offending: tuple[int, int, int] | None = None  # (pixels, row, col)
            for row in range(rows):
                for col in range(cols):
                    pixels = cell_pixels(row, col)
                    if pixels > safe_max_pixels:
                        if offending is None or pixels > offending[0]:
                            offending = (pixels, row, col)
            if offending is None:
                break

            _, row, col = offending
            # Candidate band-adjusted cuts touching this cell, ranked by
            # absolute drift from the base grid line.
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
                # No band cut to roll back; the grid estimator should have
                # prevented this earlier, but if it slipped through we mark
                # the chunk via over_safe_pixels downstream rather than loop.
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

    def _materialize(
        self,
        profile: ImageProfile,
        content_box: tuple[int, int, int, int],
        entries: list[dict],
        chunk_policy: str = "table_grid_v2",
        safe_max: int | None = None,
    ) -> list[Chunk]:
        stem_dir = self.chunks_dir / Path(profile.file_name).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        image_sha1 = _file_sha1(profile.path)
        chunks: list[Chunk] = []

        if safe_max is None:
            safe_max = self.table_cfg.safe_max_pixels
        hard_max = self.config.hard_max_pixels

        stem = Path(profile.file_name).stem
        for entry in entries:
            bbox = entry["bbox"]
            row = entry["row"]
            col = entry["col"]
            rows = entry["rows"]
            cols = entry["cols"]
            cut_source = entry["cut_source"]
            cid = _chunk_id(profile.file_name, bbox, image_sha1)
            out_path = stem_dir / traceable_chunk_name(stem, row, col, bbox)
            _save_crop(profile.path, bbox, out_path)

            ovl = overlap_dict(
                row=row,
                col=col,
                rows=rows,
                cols=cols,
                horizontal=entry["horizontal_overlap"],
                vertical=entry["vertical_overlap"],
            )

            chunk_pixels = box_pixels(bbox)

            flags: list[str] = []
            if chunk_pixels > safe_max:
                flags.append("over_safe_pixels")
            if chunk_pixels > hard_max:
                flags.append("over_hard_pixels")
            if cut_source == "grid" and (rows > 1 or cols > 1):
                flags.append("fixed_cut")
            if 0 < chunk_pixels < self.config.min_pixels:
                flags.append("small_tail")
            seen: set[str] = set()
            unique_flags: list[str] = []
            for f in flags:
                if f not in seen:
                    seen.add(f)
                    unique_flags.append(f)

            chunks.append(
                Chunk(
                    chunk_id=cid,
                    file_name=profile.file_name,
                    image_path=out_path,
                    bbox=bbox,
                    row=row,
                    col=col,
                    overlap=ovl,
                    image_sha1=image_sha1,
                    chunk_pixels=chunk_pixels,
                    is_last_row=row == rows - 1,
                    is_last_col=col == cols - 1,
                    cut_source=cut_source,
                    risk_flags=tuple(unique_flags),
                    table_group_id=entry.get("table_group_id"),
                    row_band=entry.get("row_band"),
                    col_band=entry.get("col_band"),
                    base_bbox=entry.get("base_bbox"),
                    overlap_bbox=entry.get("overlap_bbox", bbox),
                    requires_row_assembly=entry.get("requires_row_assembly", False),
                )
            )

        _write_manifest(
            stem_dir,
            profile,
            chunks,
            content_box=content_box,
            chunk_policy=chunk_policy,
        )
        return chunks


class PageChunker(TableGridChunker):
    """Normal-page chunker: prefer one full-page chunk, fall back to a light grid.

    Inherits TableGridChunker for grid helpers (_estimate_grid_shape /
    _adjust_cuts / _resolve_content_box / _materialize) but overrides chunk()
    to use the ``normal`` config section and a ``normal_page_v1`` policy.
    The legacy 4-positional constructor (max_chunk_pixels / full_page_max_pixels
    / horizontal_overlap / vertical_overlap) is preserved for callers that
    have not yet migrated to ``config=``.
    """

    def chunk(self, profile: ImageProfile, hints: LayoutHints) -> list[Chunk]:
        cfg = self.config
        normal_cfg = cfg.normal
        table_cfg = self.table_cfg

        content_box = self._resolve_content_box(profile, hints)
        cx0, cy0, cx1, cy1 = content_box
        content_width = max(1, cx1 - cx0)
        content_height = max(1, cy1 - cy0)
        content_pixels = content_width * content_height

        # Soft ceiling for grid fall-back uses target_pixels; hard_max gates
        # worst-case via the grid estimator. Full-page chunks use
        # full_page_max_pixels as their soft ceiling so a legitimate full page
        # below the policy threshold is not flagged over_safe_pixels.
        normal_safe_max = max(1, normal_cfg.target_pixels)
        full_page_safe_max = max(normal_safe_max, normal_cfg.full_page_max_pixels)

        if content_pixels <= normal_cfg.full_page_max_pixels:
            entries = [
                {
                    "bbox": content_box,
                    "row": 0,
                    "col": 0,
                    "rows": 1,
                    "cols": 1,
                    "cut_source": "full_page",
                    "horizontal_overlap": 0,
                    "vertical_overlap": 0,
                }
            ]
            return self._materialize(
                profile,
                content_box=content_box,
                entries=entries,
                chunk_policy="normal_page_v1",
                safe_max=full_page_safe_max,
            )

        overlap_x = table_cfg.horizontal_overlap
        overlap_y = table_cfg.vertical_overlap

        rows, cols = self._estimate_grid_shape(
            width=content_width,
            height=content_height,
            target_pixels=max(1, normal_cfg.target_pixels),
            safe_max_pixels=normal_safe_max,
            hard_max_pixels=max(1, cfg.hard_max_pixels),
            overlap_x=overlap_x,
            overlap_y=overlap_y,
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
            overlap_x=overlap_x,
            overlap_y=overlap_y,
            safe_max_pixels=normal_safe_max,
        )

        entries: list[dict] = []
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

                x0 = max(cx0, base_x0 - (overlap_x if col > 0 else 0))
                x1 = min(cx1, base_x1 + (overlap_x if col < cols - 1 else 0))
                y0 = max(cy0, base_y0 - (overlap_y if row > 0 else 0))
                y1 = min(cy1, base_y1 + (overlap_y if row < rows - 1 else 0))
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
                cut_source = "blank_band" if cell_uses_band else "grid"

                entries.append(
                    {
                        "bbox": (x0, y0, x1, y1),
                        "row": row,
                        "col": col,
                        "rows": rows,
                        "cols": cols,
                        "cut_source": cut_source,
                        "horizontal_overlap": overlap_x,
                        "vertical_overlap": overlap_y,
                    }
                )

        return self._materialize(
            profile,
            content_box=content_box,
            entries=entries,
            chunk_policy="normal_page_v1",
            safe_max=normal_safe_max,
        )
