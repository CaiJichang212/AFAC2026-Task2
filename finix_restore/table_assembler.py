from __future__ import annotations

import html
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rapidfuzz.distance import Levenshtein

from finix_restore.models import ChunkText
from finix_restore.table_parser import ParsedCell, ParsedChunkTables, ParsedTable, TableChunkParser


@dataclass(frozen=True)
class TableAssemblyResult:
    markdown: str
    warnings: tuple[str, ...]
    assembled_tables: int


class TableRowAssembler:
    def __init__(self) -> None:
        self.parser = TableChunkParser()

    def assemble(self, ordered_chunks: Sequence[ChunkText]) -> TableAssemblyResult:
        if not ordered_chunks:
            return TableAssemblyResult(markdown="", warnings=(), assembled_tables=0)

        groups: OrderedDict[str, list[ChunkText]] = OrderedDict()
        for chunk_text in ordered_chunks:
            key = chunk_text.chunk.table_group_id or Path(chunk_text.chunk.file_name).stem
            groups.setdefault(key, []).append(chunk_text)

        pieces: list[str] = []
        warnings: list[str] = []
        assembled_tables = 0
        for group_chunks in groups.values():
            markdown, group_warnings, group_tables = self._assemble_group(group_chunks)
            if markdown:
                pieces.append(markdown)
            warnings.extend(group_warnings)
            assembled_tables += group_tables

        return TableAssemblyResult(
            markdown="\n\n".join(piece for piece in pieces if piece),
            warnings=self._unique(warnings),
            assembled_tables=assembled_tables,
        )

    def _assemble_group(self, chunks: Sequence[ChunkText]) -> tuple[str, tuple[str, ...], int]:
        sorted_chunks = sorted(
            chunks,
            key=lambda item: (
                item.chunk.row_band if item.chunk.row_band is not None else item.chunk.row,
                item.chunk.col_band if item.chunk.col_band is not None else item.chunk.col,
            ),
        )
        parsed_chunks = [self.parser.parse(chunk) for chunk in sorted_chunks]
        warnings = [warning for parsed in parsed_chunks for warning in parsed.warnings]

        reference_chunks = [
            parsed for parsed in parsed_chunks if parsed.chunk_text.chunk.variant_kind == "full_page_reference"
        ]
        data_chunks = [
            parsed for parsed in parsed_chunks if parsed.chunk_text.chunk.variant_kind != "full_page_reference"
        ]
        if not data_chunks:
            text_blocks = self._unique_text_blocks(reference_chunks)
            return "\n".join(text_blocks), self._unique(warnings), 0

        row_bands: OrderedDict[int, list[ParsedChunkTables]] = OrderedDict()
        for parsed in data_chunks:
            row_band = parsed.chunk_text.chunk.row_band
            if row_band is None:
                row_band = parsed.chunk_text.chunk.row
            row_bands.setdefault(row_band, []).append(parsed)

        text_sources = list(reference_chunks) if reference_chunks else list(data_chunks)
        text_blocks = self._unique_text_blocks(text_sources)
        assembled_bands: list[ParsedTable | None] = []
        fallback_markdown: list[str] = []
        for band_chunks in row_bands.values():
            band_chunks = sorted(
                band_chunks,
                key=lambda item: item.chunk_text.chunk.col_band
                if item.chunk_text.chunk.col_band is not None
                else item.chunk_text.chunk.col,
            )
            assembled_table = self._assemble_row_band(band_chunks)
            if assembled_table is None:
                if len(band_chunks) > 1 and "row_alignment_uncertain" not in warnings:
                    warnings.append("row_alignment_uncertain")
                grouped_tables = self._fallback_group_by_columns(band_chunks)
                if grouped_tables:
                    assembled_bands.append(grouped_tables[0])
                    for extra in grouped_tables[1:]:
                        assembled_bands.append(extra)
                    fallback_markdown.append("")
                    if len(grouped_tables) > 1 and "fallback_multi_table_split" not in warnings:
                        warnings.append("fallback_multi_table_split")
                else:
                    fallback_text = "\n".join(parsed.chunk_text.markdown for parsed in band_chunks).strip()
                    if fallback_text and fallback_text not in text_blocks:
                        text_blocks.append(fallback_text)
            else:
                assembled_bands.append(assembled_table)

        if any(table is None for table in assembled_bands):
            markdown_parts: list[str] = []
            if text_blocks:
                markdown_parts.extend(text_blocks)
            fallback_index = 0
            for table in assembled_bands:
                if table is None:
                    if fallback_markdown[fallback_index]:
                        markdown_parts.append(fallback_markdown[fallback_index])
                    fallback_index += 1
                else:
                    markdown_parts.append(self._render_table(table.rows))
            return "\n\n".join(part for part in markdown_parts if part), self._unique(warnings), sum(
                1 for table in assembled_bands if table is not None
            )

        combined_rows: list[tuple[ParsedCell, ...]] = []
        header_key: tuple[str, ...] | None = None
        for table in assembled_bands:
            assert table is not None
            row_list = list(table.rows)
            if not row_list:
                continue
            if not combined_rows:
                combined_rows.extend(row_list)
                header_key = table.header_key
                continue
            if header_key is not None and self._row_matches_header(row_list[0], header_key):
                row_list = row_list[1:]
            for row in row_list:
                if self._is_duplicate_overlap_row(combined_rows, row):
                    continue
                combined_rows.append(row)

        markdown_parts = list(text_blocks)
        if combined_rows:
            markdown_parts.append(self._render_table(tuple(combined_rows)))
        markdown = "\n\n".join(part for part in markdown_parts if part)
        assembled_tables = 1 if combined_rows else 0
        return markdown, self._unique(warnings), assembled_tables

    def _assemble_row_band(self, parsed_chunks: Sequence[ParsedChunkTables]) -> ParsedTable | None:
        if not parsed_chunks:
            return None

        valid_chunks = [parsed for parsed in parsed_chunks if parsed.tables]
        if not valid_chunks:
            return None
        multi_table = any(len(parsed.tables) != 1 for parsed in valid_chunks)

        first_table = valid_chunks[0].tables[0]
        first_rows = first_table.rows
        if len(parsed_chunks) == 1:
            return first_table

        if not multi_table and any(
            parsed.chunk_text.chunk.anchor_bbox is not None for parsed in valid_chunks[1:]
        ):
            return self._align_by_anchor(valid_chunks)

        if multi_table:
            return self._stitch_multi_table_chunks(valid_chunks)

        return self._stitch_with_common_rows(valid_chunks)

    def _align_by_anchor(self, parsed_chunks: Sequence[ParsedChunkTables]) -> ParsedTable | None:
        merged_rows = [tuple(row) for row in parsed_chunks[0].tables[0].rows]
        for parsed in parsed_chunks[1:]:
            right_rows = parsed.tables[0].rows
            if len(merged_rows) != len(right_rows):
                return None
            scores: list[float] = []
            for left_row, right_row in zip(merged_rows, right_rows):
                if not left_row or not right_row:
                    continue
                if not left_row[0].text or not right_row[0].text:
                    continue
                scores.append(Levenshtein.normalized_similarity(left_row[0].text, right_row[0].text))
            if scores and (sum(scores) / len(scores)) < 0.80:
                return None
            updated_rows: list[tuple[ParsedCell, ...]] = []
            for left_row, right_row in zip(merged_rows, right_rows):
                tail = right_row[1:] if len(right_row) > 1 else ()
                updated_rows.append(tuple(list(left_row) + list(tail)))
            merged_rows = updated_rows
        return self._table_from_rows(tuple(merged_rows))

    def _stitch_with_common_rows(self, parsed_chunks: Sequence[ParsedChunkTables]) -> ParsedTable:
        chunk_tables = [parsed.tables[0] for parsed in parsed_chunks if parsed.tables]
        if not chunk_tables:
            return self._table_from_rows(())
        common = min(len(table.rows) for table in chunk_tables)
        stitched: list[tuple[ParsedCell, ...]] = []
        for row_index in range(common):
            merged_cells: list[ParsedCell] = []
            for table in chunk_tables:
                merged_cells.extend(table.rows[row_index])
            stitched.append(tuple(merged_cells))
        for table in chunk_tables:
            for extra_row in table.rows[common:]:
                stitched.append(tuple(extra_row))
        return self._table_from_rows(tuple(stitched))

    def _stitch_multi_table_chunks(self, parsed_chunks: Sequence[ParsedChunkTables]) -> ParsedTable:
        all_rows: list[tuple[ParsedCell, ...]] = []
        for parsed in parsed_chunks:
            for table in parsed.tables:
                for row in table.rows:
                    all_rows.append(tuple(row))
        return self._table_from_rows(tuple(all_rows))

    def _fallback_group_by_columns(
        self, band_chunks: Sequence[ParsedChunkTables]
    ) -> list[ParsedTable]:
        buckets: dict[int, list[tuple[ParsedCell, ...]]] = {}
        for parsed in band_chunks:
            for table in parsed.tables:
                for row in table.rows:
                    if not row:
                        continue
                    buckets.setdefault(len(row), []).append(tuple(row))
        if not buckets:
            return []
        ordered = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
        tables: list[ParsedTable] = []
        for _, rows in ordered:
            tables.append(self._table_from_rows(tuple(rows)))
        return tables

    def _render_table(self, rows: tuple[tuple[ParsedCell, ...], ...]) -> str:
        row_html = []
        for row in rows:
            cells_html: list[str] = []
            for cell in row:
                tag = "th" if cell.is_header else "td"
                attrs: list[str] = []
                if cell.colspan > 1:
                    attrs.append(f' colspan="{cell.colspan}"')
                if cell.rowspan > 1:
                    attrs.append(f' rowspan="{cell.rowspan}"')
                text = html.escape(cell.text)
                cells_html.append(f"<{tag}{''.join(attrs)}>{text}</{tag}>")
            row_html.append(f"<tr>{''.join(cells_html)}</tr>")
        return f"<table>{''.join(row_html)}</table>"

    def _table_from_rows(self, rows: tuple[tuple[ParsedCell, ...], ...]) -> ParsedTable:
        header_key = tuple(cell.text for cell in rows[0]) if rows else ()
        return ParsedTable(rows=rows, raw_html="", header_key=header_key, broken=False)

    def _unique_text_blocks(self, parsed_chunks: Sequence[ParsedChunkTables]) -> list[str]:
        seen: set[str] = set()
        blocks: list[str] = []
        for parsed in parsed_chunks:
            for raw_text in (parsed.leading_text, parsed.trailing_text):
                text = raw_text.strip()
                if text and text not in seen:
                    seen.add(text)
                    blocks.append(text)
        return blocks

    def _row_signature(self, row: tuple[ParsedCell, ...]) -> str:
        non_empty = [cell.text.strip() for cell in row if cell.text.strip()]
        return "|".join(non_empty[:3])

    def _row_matches_header(self, row: tuple[ParsedCell, ...], header_key: tuple[str, ...]) -> bool:
        header_signature = "|".join(item.strip() for item in header_key[:3] if item.strip())
        row_signature = self._row_signature(row)
        if not header_signature or not row_signature:
            return False
        return Levenshtein.normalized_similarity(row_signature, header_signature) >= 0.92

    def _is_duplicate_overlap_row(
        self,
        existing_rows: Sequence[tuple[ParsedCell, ...]],
        candidate_row: tuple[ParsedCell, ...],
    ) -> bool:
        candidate_signature = self._row_signature(candidate_row)
        if not candidate_signature:
            return False
        for previous_row in existing_rows[-3:]:
            previous_signature = self._row_signature(previous_row)
            if previous_signature and Levenshtein.normalized_similarity(candidate_signature, previous_signature) >= 0.92:
                return True
        return False

    def _unique(self, warnings: Sequence[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for warning in warnings:
            if warning not in seen:
                seen.add(warning)
                ordered.append(warning)
        return tuple(ordered)
