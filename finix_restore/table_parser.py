from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from finix_restore.models import ChunkText


_TABLE_FRAGMENT_RE = re.compile(r"<table\b.*?(?:</table>|$)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ParsedCell:
    text: str
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False


@dataclass(frozen=True)
class ParsedTable:
    rows: tuple[tuple[ParsedCell, ...], ...]
    raw_html: str
    header_key: tuple[str, ...]
    broken: bool


@dataclass(frozen=True)
class ParsedChunkTables:
    chunk_text: ChunkText
    leading_text: str
    tables: tuple[ParsedTable, ...]
    trailing_text: str
    warnings: tuple[str, ...]


class TableChunkParser:
    def parse(self, chunk_text: ChunkText) -> ParsedChunkTables:
        markdown = chunk_text.markdown
        matches = list(_TABLE_FRAGMENT_RE.finditer(markdown))
        if not matches:
            return ParsedChunkTables(
                chunk_text=chunk_text,
                leading_text=markdown,
                tables=(),
                trailing_text="",
                warnings=(),
            )

        leading_text = markdown[: matches[0].start()]
        trailing_parts: list[str] = []
        parsed_tables: list[ParsedTable] = []
        warnings: list[str] = []

        for index, match in enumerate(matches):
            if index > 0:
                trailing_parts.append(markdown[matches[index - 1].end() : match.start()])
            fragment = match.group(0)
            parsed, table_warnings = self._parse_table(fragment)
            parsed_tables.append(parsed)
            if parsed.broken and "html_broken" not in warnings:
                warnings.append("html_broken")
            for warning in table_warnings:
                if warning not in warnings:
                    warnings.append(warning)

        trailing_parts.append(markdown[matches[-1].end() :])
        return ParsedChunkTables(
            chunk_text=chunk_text,
            leading_text=leading_text,
            tables=tuple(parsed_tables),
            trailing_text="".join(trailing_parts),
            warnings=tuple(warnings),
        )

    def _parse_table(self, fragment: str) -> tuple[ParsedTable, tuple[str, ...]]:
        broken = self._is_broken(fragment)
        soup = BeautifulSoup(fragment, "html.parser")
        table = soup.find("table")
        rows: list[tuple[ParsedCell, ...]] = []
        warnings: list[str] = []
        if table is not None:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                parsed_cells: list[ParsedCell] = []
                for cell in cells:
                    colspan, colspan_warning = self._parse_span(cell.get("colspan"))
                    rowspan, rowspan_warning = self._parse_span(cell.get("rowspan"))
                    if colspan_warning and colspan_warning not in warnings:
                        warnings.append(colspan_warning)
                    if rowspan_warning and rowspan_warning not in warnings:
                        warnings.append(rowspan_warning)
                    parsed_cells.append(
                        ParsedCell(
                            text=cell.get_text().strip(),
                            colspan=colspan,
                            rowspan=rowspan,
                            is_header=cell.name == "th",
                        )
                    )
                rows.append(tuple(parsed_cells))
        row_tuple = tuple(rows)
        header_key = tuple(cell.text for cell in row_tuple[0]) if row_tuple else ()
        return (
            ParsedTable(
                rows=row_tuple,
                raw_html=fragment,
                header_key=header_key,
                broken=broken,
            ),
            tuple(warnings),
        )

    def _parse_span(self, raw: str | None) -> tuple[int, str | None]:
        if raw is None:
            return 1, None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 1, "invalid_span"
        if value < 1:
            return 1, "invalid_span"
        return value, None

    def _is_broken(self, fragment: str) -> bool:
        lowered = fragment.lower()
        for tag in ("table", "tr", "td", "th"):
            opens = len(re.findall(fr"<{tag}\b", lowered))
            closes = lowered.count(f"</{tag}>")
            if closes < opens:
                return True
        return False
