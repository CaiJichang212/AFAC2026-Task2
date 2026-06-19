from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from finix_restore.chunk_geometry import box_pixels
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
    def __init__(self, chunks_dir: Path, window_height: int = 4000, overlap: int = 320) -> None:
        self.chunks_dir = Path(chunks_dir)
        self.window_height = window_height
        self.overlap = overlap

    def chunk(self, profile: ImageProfile, hints: LayoutHints) -> list[Chunk]:
        stem_dir = self.chunks_dir / Path(profile.file_name).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        image_sha1 = _file_sha1(profile.path)
        chunks: list[Chunk] = []
        y0 = 0
        row = 0
        while y0 < profile.height:
            y1 = min(profile.height, y0 + self.window_height)
            cut_source = "dynamic_window"
            if y1 < profile.height:
                adjusted_y1 = self._adjust_to_blank_band(y1, hints.horizontal_blank_bands)
                if adjusted_y1 != y1:
                    cut_source = "blank_band"
                y1 = adjusted_y1
            bbox = (0, y0, profile.width, y1)
            cid = _chunk_id(profile.file_name, bbox, image_sha1)
            out_path = stem_dir / f"{cid}.jpg"
            _save_crop(profile.path, bbox, out_path)
            is_last_row = y1 >= profile.height
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    file_name=profile.file_name,
                    image_path=out_path,
                    bbox=bbox,
                    row=row,
                    col=0,
                    overlap={"top": self.overlap if y0 else 0, "bottom": self.overlap if y1 < profile.height else 0},
                    image_sha1=image_sha1,
                    chunk_pixels=box_pixels(bbox),
                    is_last_row=is_last_row,
                    is_last_col=True,
                    cut_source=cut_source,
                    risk_flags=(),
                )
            )
            if y1 >= profile.height:
                break
            y0 = max(y1 - self.overlap, y0 + 1)
            row += 1
        _write_manifest(
            stem_dir,
            profile,
            chunks,
            content_box=(0, 0, profile.width, profile.height),
            chunk_policy="long_dynamic_v1",
        )
        return chunks

    def _adjust_to_blank_band(self, y: int, bands: list[tuple[int, int]]) -> int:
        candidates = [band for band in bands if abs(((band[0] + band[1]) // 2) - y) <= self.overlap]
        if not candidates:
            return y
        band = min(candidates, key=lambda b: abs(((b[0] + b[1]) // 2) - y))
        return max(1, (band[0] + band[1]) // 2)


class TableGridChunker:
    def __init__(
        self,
        chunks_dir: Path,
        max_chunk_pixels: int = 12_000_000,
        full_page_max_pixels: int = 16_000_000,
        horizontal_overlap: int = 160,
        vertical_overlap: int = 220,
    ) -> None:
        self.chunks_dir = Path(chunks_dir)
        self.max_chunk_pixels = max_chunk_pixels
        self.full_page_max_pixels = full_page_max_pixels
        self.horizontal_overlap = horizontal_overlap
        self.vertical_overlap = vertical_overlap

    def chunk(self, profile: ImageProfile, hints: LayoutHints) -> list[Chunk]:
        if profile.pixels <= self.full_page_max_pixels:
            boxes = [(0, 0, profile.width, profile.height, 0, 0)]
            rows, cols = 1, 1
            cut_source = "full_page"
        else:
            cols = max(1, math.ceil(math.sqrt(profile.pixels / self.max_chunk_pixels)))
            rows = max(1, math.ceil(profile.pixels / (cols * self.max_chunk_pixels)))
            boxes = []
            for row in range(rows):
                base_y0 = row * profile.height // rows
                base_y1 = (row + 1) * profile.height // rows
                for col in range(cols):
                    base_x0 = col * profile.width // cols
                    base_x1 = (col + 1) * profile.width // cols
                    x0 = max(0, base_x0 - (self.horizontal_overlap if col else 0))
                    x1 = min(profile.width, base_x1 + (self.horizontal_overlap if col < cols - 1 else 0))
                    y0 = max(0, base_y0 - (self.vertical_overlap if row else 0))
                    y1 = min(profile.height, base_y1 + (self.vertical_overlap if row < rows - 1 else 0))
                    boxes.append((x0, y0, x1, y1, row, col))
            cut_source = "grid"
        return self._materialize(profile, boxes, rows=rows, cols=cols, cut_source=cut_source)

    def _materialize(
        self,
        profile: ImageProfile,
        boxes: list[tuple[int, int, int, int, int, int]],
        rows: int,
        cols: int,
        cut_source: str,
    ) -> list[Chunk]:
        stem_dir = self.chunks_dir / Path(profile.file_name).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        image_sha1 = _file_sha1(profile.path)
        chunks: list[Chunk] = []
        for x0, y0, x1, y1, row, col in boxes:
            bbox = (x0, y0, x1, y1)
            cid = _chunk_id(profile.file_name, bbox, image_sha1)
            out_path = stem_dir / f"{cid}.jpg"
            _save_crop(profile.path, bbox, out_path)
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    file_name=profile.file_name,
                    image_path=out_path,
                    bbox=bbox,
                    row=row,
                    col=col,
                    overlap={
                        "left": self.horizontal_overlap if col else 0,
                        "right": self.horizontal_overlap,
                        "top": self.vertical_overlap if row else 0,
                        "bottom": self.vertical_overlap,
                    },
                    image_sha1=image_sha1,
                    chunk_pixels=box_pixels(bbox),
                    is_last_row=row == rows - 1,
                    is_last_col=col == cols - 1,
                    cut_source=cut_source,
                    risk_flags=(),
                )
            )
        _write_manifest(
            stem_dir,
            profile,
            chunks,
            content_box=(0, 0, profile.width, profile.height),
            chunk_policy="table_grid_v2",
        )
        return chunks


class PageChunker(TableGridChunker):
    pass
