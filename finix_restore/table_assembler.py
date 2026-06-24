from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from finix_restore.models import ChunkText
from finix_restore.table_parser import ParsedChunkTables, TableChunkParser


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

        row_bands: OrderedDict[int, list[ParsedChunkTables]] = OrderedDict()
        for parsed in parsed_chunks:
            row_band = parsed.chunk_text.chunk.row_band
            if row_band is None:
                row_band = parsed.chunk_text.chunk.row
            row_bands.setdefault(row_band, []).append(parsed)

        assembled_band_rows: list[tuple[tuple[str, ...], ...] | None] = []
        band_markdown: list[str] = []
        for band_chunks in row_bands.values():
            band_chunks = sorted(
                band_chunks,
                key=lambda item: item.chunk_text.chunk.col_band
                if item.chunk_text.chunk.col_band is not None
                else item.chunk_text.chunk.col,
            )
            assembled_rows = self._assemble_row_band(band_chunks)
            if assembled_rows is None:
                if len(band_chunks) > 1 and "row_alignment_uncertain" not in warnings:
                    warnings.append("row_alignment_uncertain")
                band_markdown.append("\n".join(parsed.chunk_text.markdown for parsed in band_chunks))
                assembled_band_rows.append(None)
            else:
                assembled_band_rows.append(assembled_rows)

        if any(rows is None for rows in assembled_band_rows):
            markdown_parts: list[str] = []
            band_index = 0
            for rows in assembled_band_rows:
                if rows is None:
                    markdown_parts.append(band_markdown[band_index])
                    band_index += 1
                else:
                    markdown_parts.append(self._render_table(rows))
            return "\n".join(markdown_parts), self._unique(warnings), sum(1 for rows in assembled_band_rows if rows)

        combined_rows: list[tuple[str, ...]] = []
        header_key: tuple[str, ...] | None = None
        for rows in assembled_band_rows:
            assert rows is not None
            row_list = list(rows)
            if not row_list:
                continue
            if not combined_rows:
                combined_rows.extend(row_list)
                header_key = row_list[0]
                continue
            if header_key is not None and row_list[0] == header_key:
                row_list = row_list[1:]
            combined_rows.extend(row_list)

        markdown = self._render_table(tuple(combined_rows)) if combined_rows else ""
        assembled_tables = 1 if combined_rows else 0
        return markdown, self._unique(warnings), assembled_tables

    def _assemble_row_band(self, parsed_chunks: Sequence[ParsedChunkTables]) -> tuple[tuple[str, ...], ...] | None:
        if not parsed_chunks:
            return ()

        if any(parsed.leading_text.strip() or parsed.trailing_text.strip() for parsed in parsed_chunks):
            return None
        if any(len(parsed.tables) != 1 for parsed in parsed_chunks):
            return None

        first_rows = parsed_chunks[0].tables[0].rows
        if len(parsed_chunks) == 1:
            return first_rows

        row_count = len(first_rows)
        if row_count == 0:
            return ()
        if any(len(parsed.tables[0].rows) != row_count for parsed in parsed_chunks[1:]):
            return None

        stitched_rows: list[tuple[str, ...]] = []
        for row_index in range(row_count):
            merged_cells: list[str] = []
            for parsed in parsed_chunks:
                merged_cells.extend(parsed.tables[0].rows[row_index])
            stitched_rows.append(tuple(merged_cells))
        return tuple(stitched_rows)

    def _render_table(self, rows: tuple[tuple[str, ...], ...]) -> str:
        row_html = []
        for row in rows:
            cell_html = "".join(f"<td>{cell}</td>" for cell in row)
            row_html.append(f"<tr>{cell_html}</tr>")
        return f"<table>{''.join(row_html)}</table>"

    def _unique(self, warnings: Sequence[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for warning in warnings:
            if warning not in seen:
                seen.add(warning)
                ordered.append(warning)
        return tuple(ordered)
