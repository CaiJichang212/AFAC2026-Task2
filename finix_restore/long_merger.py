from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from finix_restore.dedup import DedupMerger
from finix_restore.models import ChunkText
from finix_restore.table_parser import ParsedTable, TableChunkParser


@dataclass(frozen=True)
class LongMergeResult:
    markdown: str
    warnings: Sequence[str]
    merged_tables: int
    removed_table_fragments: int
    removed_text_blocks: int


@dataclass(frozen=True)
class _OutputSegment:
    kind: str
    markdown: str
    chunk_text: ChunkText
    table: ParsedTable | None = None


class LongStripMerger:
    def __init__(
        self,
        dedup: DedupMerger | None = None,
        table_parser: TableChunkParser | None = None,
    ) -> None:
        self.dedup = dedup or DedupMerger()
        self.table_parser = table_parser or TableChunkParser()

    def merge(self, ordered_chunks: Sequence[ChunkText]) -> LongMergeResult:
        if not ordered_chunks:
            return LongMergeResult(
                markdown="",
                warnings=(),
                merged_tables=0,
                removed_table_fragments=0,
                removed_text_blocks=0,
            )

        warnings: list[str] = []
        output: list[_OutputSegment] = []
        merged_tables = 0
        removed_table_fragments = 0
        removed_text_blocks = 0

        for chunk_text in ordered_chunks:
            parsed = self.table_parser.parse(chunk_text)
            warnings.extend(parsed.warnings)
            if parsed.leading_text:
                removed_text_blocks += self._append_text(output, chunk_text, parsed.leading_text)
            for table in parsed.tables:
                segment = _OutputSegment(
                    kind="table",
                    markdown=table.raw_html,
                    chunk_text=chunk_text,
                    table=table,
                )
                if output and output[-1].kind == "table":
                    merged = self._merge_tables(output[-1], segment)
                    if merged is None:
                        if "long_table_alignment_uncertain" not in warnings:
                            warnings.append("long_table_alignment_uncertain")
                        output.append(segment)
                    else:
                        output[-1] = merged
                        merged_tables += 1
                        removed_table_fragments += 1
                else:
                    output.append(segment)
            if parsed.trailing_text:
                removed_text_blocks += self._append_text(output, chunk_text, parsed.trailing_text)

        markdown = self._render(output)
        return LongMergeResult(
            markdown=markdown,
            warnings=tuple(dict.fromkeys(warnings)),
            merged_tables=merged_tables,
            removed_table_fragments=removed_table_fragments,
            removed_text_blocks=removed_text_blocks,
        )

    def _append_text(
        self,
        output: list[_OutputSegment],
        chunk_text: ChunkText,
        markdown: str,
    ) -> int:
        if not markdown.strip():
            return 0
        body_chunk = ChunkText(
            chunk=chunk_text.chunk,
            markdown=markdown,
            block_type="body",
            source=chunk_text.source,
        )
        if output and output[-1].kind == "text":
            merged = self.dedup.merge([output[-1].chunk_text, body_chunk])
            output[-1] = _OutputSegment(
                kind="text",
                markdown=merged.markdown.rstrip(),
                chunk_text=ChunkText(
                    chunk=body_chunk.chunk,
                    markdown=merged.markdown.rstrip(),
                    block_type="body",
                    source=body_chunk.source,
                ),
            )
            return len(merged.removed_ranges)

        output.append(
            _OutputSegment(
                kind="text",
                markdown=markdown.strip(),
                chunk_text=body_chunk,
            )
        )
        return 0

    def _merge_tables(self, left: _OutputSegment, right: _OutputSegment) -> _OutputSegment | None:
        left_table = left.table
        right_table = right.table
        if left_table is None or right_table is None:
            return None
        if not self._can_merge_tables(left_table, right_table):
            return None

        left_rows = list(left_table.rows)
        right_rows = list(right_table.rows)
        if left_table.header_key and right_rows and tuple(right_rows[0]) == tuple(left_table.header_key):
            right_rows = right_rows[1:]
        merged_rows = tuple(left_rows + right_rows)
        merged_table = ParsedTable(
            rows=merged_rows,
            raw_html=self._render_table(merged_rows),
            header_key=left_table.header_key,
            broken=left_table.broken or right_table.broken,
        )
        return _OutputSegment(
            kind="table",
            markdown=merged_table.raw_html,
            chunk_text=right.chunk_text,
            table=merged_table,
        )

    def _can_merge_tables(self, left: ParsedTable, right: ParsedTable) -> bool:
        if left.header_key and right.header_key and left.header_key == right.header_key:
            return True
        if not left.rows or not right.rows:
            return False
        left_col_count = len(left.rows[0])
        right_col_count = len(right.rows[0])
        if left_col_count != right_col_count:
            return False
        left_last_row = left.rows[-1] if left.rows else ()
        right_first_row = right.rows[0] if right.rows else ()
        return bool(left_last_row and right_first_row and left_last_row == right_first_row)

    def _render(self, segments: Sequence[_OutputSegment]) -> str:
        pieces = [segment.markdown.strip() for segment in segments if segment.markdown.strip()]
        if not pieces:
            return ""
        return "\n\n".join(pieces).strip() + "\n"

    def _render_table(self, rows: Sequence[Sequence[str]]) -> str:
        row_html: list[str] = []
        for row in rows:
            cells = "".join(f"<td>{cell}</td>" for cell in row)
            row_html.append(f"<tr>{cells}</tr>")
        return f"<table>{''.join(row_html)}</table>"
