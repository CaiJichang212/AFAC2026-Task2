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
    tag: str = "td"


ParsedRow = tuple[ParsedCell, ...]


@dataclass(frozen=True)
class ParsedTable:
    rows: tuple[tuple[str, ...], ...]
    raw_html: str
    header_key: tuple[str, ...]
    broken: bool
    structured_rows: tuple[ParsedRow, ...] = ()


@dataclass(frozen=True)
class ParsedChunkTables:
    chunk_text: ChunkText
    leading_text: str
    tables: tuple[ParsedTable, ...]
    trailing_text: str
    warnings: tuple[str, ...]
    following_texts: tuple[str, ...] = ()


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
        following_texts: list[str] = []
        parsed_tables: list[ParsedTable] = []
        warnings: list[str] = []

        for index, match in enumerate(matches):
            fragment = match.group(0)
            parsed = self._parse_table(fragment)
            parsed_tables.append(parsed)
            if parsed.broken and "html_broken" not in warnings:
                warnings.append("html_broken")
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            following_texts.append(markdown[match.end() : next_start])

        trailing_text = following_texts[-1] if following_texts else ""
        return ParsedChunkTables(
            chunk_text=chunk_text,
            leading_text=leading_text,
            tables=tuple(parsed_tables),
            trailing_text=trailing_text,
            warnings=tuple(warnings),
            following_texts=tuple(following_texts),
        )

    def _parse_table(self, fragment: str) -> ParsedTable:
        broken = self._is_broken(fragment)
        soup = BeautifulSoup(fragment, "html.parser")
        table = soup.find("table")
        rows: list[tuple[str, ...]] = []
        structured_rows: list[ParsedRow] = []
        if table is not None:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                parsed_cells = tuple(
                    ParsedCell(
                        text=cell.get_text().strip(),
                        colspan=self._parse_span(cell.get("colspan")),
                        rowspan=self._parse_span(cell.get("rowspan")),
                        tag=cell.name or "td",
                    )
                    for cell in cells
                )
                structured_rows.append(parsed_cells)
                rows.append(tuple(cell.text for cell in parsed_cells))
        row_tuple = tuple(rows)
        header_key = row_tuple[0] if row_tuple else ()
        return ParsedTable(
            rows=row_tuple,
            raw_html=fragment,
            header_key=header_key,
            broken=broken,
            structured_rows=tuple(structured_rows),
        )

    def _parse_span(self, value: object) -> int:
        try:
            return max(1, int(str(value)))
        except (TypeError, ValueError):
            return 1

    def _is_broken(self, fragment: str) -> bool:
        lowered = fragment.lower()
        for tag in ("table", "tr", "td", "th"):
            opens = len(re.findall(fr"<{tag}\b", lowered))
            closes = lowered.count(f"</{tag}>")
            if closes < opens:
                return True
        return False
