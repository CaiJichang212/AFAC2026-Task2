from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


DocType = Literal["long_strip", "table_page", "normal_page", "unknown"]
RiskLevel = Literal["low", "medium", "high", "extreme"]


@dataclass(frozen=True)
class ImageProfile:
    file_name: str
    path: Path
    width: int
    height: int
    pixels: int
    aspect: float
    doc_type: DocType
    risk_level: RiskLevel


@dataclass(frozen=True)
class LayoutHints:
    crop_box: tuple[int, int, int, int]
    horizontal_blank_bands: list[tuple[int, int]]
    vertical_blank_bands: list[tuple[int, int]]
    table_line_density: float
    column_count: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    file_name: str
    image_path: Path
    bbox: tuple[int, int, int, int]
    row: int
    col: int
    overlap: dict[str, int]
    image_sha1: str
    chunk_pixels: int = 0
    is_last_row: bool = False
    is_last_col: bool = False
    cut_source: str = "unknown"
    risk_flags: tuple[str, ...] = ()
    table_group_id: str | None = None
    row_band: int | None = None
    col_band: int | None = None
    base_bbox: tuple[int, int, int, int] | None = None
    overlap_bbox: tuple[int, int, int, int] | None = None
    requires_row_assembly: bool = False
    sent_width: int | None = None
    sent_height: int | None = None
    render_scale: float = 1.0
    variant_kind: str | None = None
    anchor_bbox: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class ChunkText:
    chunk: Chunk
    markdown: str
    block_type: Literal["body", "toc", "table", "header_footer", "unknown"]
    source: Literal["api", "cache", "manual_fixture"]


@dataclass(frozen=True)
class MergeResult:
    markdown: str
    removed_ranges: list[tuple[str, int, int]]
    warnings: list[str]


@dataclass(frozen=True)
class TableRepairResult:
    markdown: str
    repaired_tags: int
    warnings: list[str]


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    risks: list[str]
    metrics: dict[str, float | int | str]


@dataclass(frozen=True)
class ProcessedFile:
    file_name: str
    markdown: str
    quality: QualityReport
    rerun_count: int = 0
