from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Sequence

from finix_restore.dedup import DedupMerger
from finix_restore.models import ChunkText
from finix_restore.table_parser import ParsedCell, ParsedRow, ParsedTable, TableChunkParser


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


@dataclass(frozen=True)
class _PendingTableText:
    rows: tuple[ParsedRow, ...]
    remaining_markdown: str = ""


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
            for table_index, table in enumerate(parsed.tables):
                segment = _OutputSegment(
                    kind="table",
                    markdown=table.raw_html,
                    chunk_text=chunk_text,
                    table=table,
                )
                merged = self._append_or_merge_table(output, segment)
                if merged:
                    merged_tables += 1
                    removed_table_fragments += 1
                elif len(output) >= 2 and output[-2].kind == "table":
                    if "long_table_alignment_uncertain" not in warnings:
                        warnings.append("long_table_alignment_uncertain")
                following = parsed.following_texts[table_index] if table_index < len(parsed.following_texts) else ""
                if table_index < len(parsed.tables) - 1 and following.strip():
                    removed_text_blocks += self._append_text(output, chunk_text, following)
            if parsed.trailing_text:
                removed_text_blocks += self._append_text(output, chunk_text, parsed.trailing_text)

        markdown = self._render(output)
        markdown, removed_dupes = self._collapse_near_duplicate_blocks(markdown)
        removed_text_blocks += removed_dupes
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

    def _append_or_merge_table(self, output: list[_OutputSegment], segment: _OutputSegment) -> bool:
        if output and output[-1].kind == "text" and len(output) >= 2 and output[-2].kind == "table":
            left = output[-2]
            if (
                segment.table is not None
                and left.table is not None
                and self._can_merge_tables(left.table, segment.table)
            ):
                pending = self._pending_table_text(output[-1].markdown)
                if pending is not None:
                    self._consume_pending_text(output, pending)
                    titled = self._prepend_title_rows_to_table(segment, pending)
                    if titled is not None:
                        segment = titled
        elif (
            output
            and output[-1].kind == "text"
            and segment.table is not None
            and self._table_col_count(segment.table) >= 4
        ):
            pending = self._pending_table_text(output[-1].markdown)
            if pending is not None:
                self._consume_pending_text(output, pending)
                titled = self._prepend_title_rows_to_table(segment, pending)
                if titled is not None:
                    segment = titled

        if output and output[-1].kind == "table":
            merged = self._merge_tables(output[-1], segment)
            if merged is not None:
                output[-1] = merged
                return True

        output.append(segment)
        return False

    def _consume_pending_text(self, output: list[_OutputSegment], pending: _PendingTableText) -> None:
        if not output or output[-1].kind != "text":
            return
        if pending.remaining_markdown:
            output[-1] = _OutputSegment(
                kind="text",
                markdown=pending.remaining_markdown,
                chunk_text=ChunkText(
                    chunk=output[-1].chunk_text.chunk,
                    markdown=pending.remaining_markdown,
                    block_type="body",
                    source=output[-1].chunk_text.source,
                ),
            )
        else:
            output.pop()

    def _merge_tables(self, left: _OutputSegment, right: _OutputSegment) -> _OutputSegment | None:
        left_table = left.table
        right_table = right.table
        if left_table is None or right_table is None:
            return None
        if not self._can_merge_tables(left_table, right_table):
            return None

        left_rows = list(self._structured_rows(left_table))
        right_rows = list(self._structured_rows(right_table))
        right_rows = self._drop_duplicate_leading_rows(left_rows, right_rows, left_table.header_key)
        merged_rows = tuple(left_rows + right_rows)
        merged_table = self._table_from_structured_rows(
            merged_rows,
            broken=left_table.broken or right_table.broken,
            header_key=left_table.header_key or right_table.header_key,
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
        if self._has_duplicate_boundary(left, right):
            return True
        left_col_count = self._table_col_count(left)
        right_col_count = self._table_col_count(right)
        if left_col_count == right_col_count and left_col_count >= 4:
            return True
        if self._is_single_colspan_table(left, right_col_count) or self._is_single_colspan_table(right, left_col_count):
            return True
        return False

    def _has_duplicate_boundary(self, left: ParsedTable, right: ParsedTable) -> bool:
        left_rows = self._structured_rows(left)
        right_rows = self._structured_rows(right)
        if not left_rows or not right_rows:
            return False
        left_texts = [self._row_text(row) for row in left_rows[-5:]]
        right_first = self._row_text(right_rows[0])
        return bool(right_first and right_first in left_texts)

    def _is_single_colspan_table(self, table: ParsedTable, col_count: int) -> bool:
        rows = self._structured_rows(table)
        if not rows or col_count < 2:
            return False
        return all(len(row) == 1 and row[0].colspan == col_count for row in rows)

    def _append_title_rows_to_table(self, segment: _OutputSegment, pending: _PendingTableText) -> _OutputSegment | None:
        return self._with_title_rows(segment, pending, prepend=False)

    def _prepend_title_rows_to_table(self, segment: _OutputSegment, pending: _PendingTableText) -> _OutputSegment | None:
        return self._with_title_rows(segment, pending, prepend=True)

    def _with_title_rows(
        self,
        segment: _OutputSegment,
        pending: _PendingTableText,
        *,
        prepend: bool,
    ) -> _OutputSegment | None:
        table = segment.table
        if table is None:
            return None
        col_count = self._table_col_count(table)
        if col_count < 2:
            return None
        title_rows: list[ParsedRow] = []
        for pending_row in pending.rows:
            title = self._row_text(pending_row)
            if not title:
                continue
            if len(pending_row) == 1:
                title_rows.append((ParsedCell(text=title, colspan=col_count),))
            else:
                title_rows.append(pending_row)
        rows = list(self._structured_rows(table))
        if prepend:
            rows = title_rows + rows
        else:
            for title_row in title_rows:
                if not rows or self._row_text(rows[-1]) != self._row_text(title_row):
                    rows.append(title_row)
        merged_table = self._table_from_structured_rows(
            tuple(rows),
            broken=table.broken,
            header_key=table.header_key,
        )
        return _OutputSegment(
            kind="table",
            markdown=merged_table.raw_html,
            chunk_text=segment.chunk_text,
            table=merged_table,
        )

    def _pending_table_text(self, markdown: str) -> _PendingTableText | None:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        if not lines:
            return None
        title_lines: list[str] = []
        remaining_lines: list[str] = []
        for line in lines:
            text = line.lstrip("# ").strip()
            is_heading = line.lstrip().startswith("#")
            looks_like_section = any(marker in text for marker in ("癌（", "年龄", "分化型", "所有年龄组"))
            if (
                text
                and len(text) <= 40
                and (is_heading or looks_like_section)
                and not any(marker in text for marker in ("。", "；", "，"))
            ):
                title_lines.append(text)
            else:
                remaining_lines.append(line)
        if not title_lines or len(title_lines) > 3:
            return None
        rows = tuple((ParsedCell(text=line),) for line in title_lines)
        return _PendingTableText(rows=rows, remaining_markdown="\n".join(remaining_lines))

    def _drop_duplicate_leading_rows(
        self,
        left_rows: Sequence[ParsedRow],
        right_rows: Sequence[ParsedRow],
        header_key: tuple[str, ...],
    ) -> list[ParsedRow]:
        rows = list(right_rows)
        if header_key and rows and self._row_texts(rows[0]) == header_key:
            rows = rows[1:]
        max_match = min(len(left_rows), len(rows), 5)
        for size in range(max_match, 0, -1):
            if [self._row_text(row) for row in left_rows[-size:]] == [self._row_text(row) for row in rows[:size]]:
                return rows[size:]
        return rows

    def _table_from_structured_rows(
        self,
        rows: tuple[ParsedRow, ...],
        *,
        broken: bool,
        header_key: tuple[str, ...],
    ) -> ParsedTable:
        text_rows = tuple(tuple(cell.text for cell in row) for row in rows)
        resolved_header = header_key or (text_rows[0] if text_rows else ())
        return ParsedTable(
            rows=text_rows,
            raw_html=self._render_table(rows),
            header_key=resolved_header,
            broken=broken,
            structured_rows=rows,
        )

    def _structured_rows(self, table: ParsedTable) -> tuple[ParsedRow, ...]:
        if table.structured_rows:
            return table.structured_rows
        return tuple(tuple(ParsedCell(text=cell) for cell in row) for row in table.rows)

    def _table_col_count(self, table: ParsedTable) -> int:
        rows = self._structured_rows(table)
        return max((sum(cell.colspan for cell in row) for row in rows), default=0)

    def _row_texts(self, row: ParsedRow) -> tuple[str, ...]:
        return tuple(cell.text for cell in row)

    def _row_text(self, row: ParsedRow) -> str:
        return "|".join(cell.text for cell in row)

    def _render(self, segments: Sequence[_OutputSegment]) -> str:
        pieces = [segment.markdown.strip() for segment in segments if segment.markdown.strip()]
        if not pieces:
            return ""
        return "\n\n".join(pieces).strip() + "\n"

    def _collapse_near_duplicate_blocks(self, markdown: str) -> tuple[str, int]:
        if not markdown.strip():
            return markdown, 0
        blocks = self._split_text_blocks(markdown)
        kept: list[tuple[str, str]] = []
        recent_keys: list[str] = []
        removed = 0
        for raw, key in blocks:
            if key and key in recent_keys:
                removed += 1
                continue
            kept.append((raw, key))
            if key:
                recent_keys.append(key)
                if len(recent_keys) > 6:
                    recent_keys.pop(0)
        rebuilt = "\n\n".join(raw for raw, _ in kept).strip()
        if markdown.endswith("\n") and rebuilt:
            rebuilt += "\n"
        return rebuilt, removed

    def _split_text_blocks(self, markdown: str) -> list[tuple[str, str]]:
        text = markdown.replace("\r\n", "\n").replace("\r", "\n")
        blocks: list[tuple[str, str]] = []
        pos = 0
        for match in re.finditer(r"<table\b.*?</table>", text, flags=re.IGNORECASE | re.DOTALL):
            preceding = text[pos : match.start()]
            for block in re.split(r"\n\s*\n+", preceding):
                stripped = block.strip()
                if stripped:
                    blocks.append((stripped, self._block_key(stripped)))
            blocks.append((match.group(0), ""))
            pos = match.end()
        tail = text[pos:]
        for block in re.split(r"\n\s*\n+", tail):
            stripped = block.strip()
            if stripped:
                blocks.append((stripped, self._block_key(stripped)))
        return blocks

    def _block_key(self, text: str) -> str:
        # 仅对短小且可能跨块重复出现的标题/单行段落做去重，避免误删长正文。
        if "<table" in text.lower():
            return ""
        if "\n" in text:
            return ""
        if len(text) > 80:
            return ""
        return re.sub(r"\s+", "", text)

    def _render_table(self, rows: Sequence[ParsedRow]) -> str:
        row_html: list[str] = []
        for row in rows:
            cells: list[str] = []
            for cell in row:
                attrs = []
                if cell.colspan > 1:
                    attrs.append(f'colspan="{cell.colspan}"')
                if cell.rowspan > 1:
                    attrs.append(f'rowspan="{cell.rowspan}"')
                attr_text = f" {' '.join(attrs)}" if attrs else ""
                tag = "th" if cell.tag == "th" else "td"
                cells.append(f"<{tag}{attr_text}>{escape(cell.text)}</{tag}>")
            row_html.append(f"<tr>{''.join(cells)}</tr>")
        return f"<table>{''.join(row_html)}</table>"
