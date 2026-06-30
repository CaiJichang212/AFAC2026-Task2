from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString

from finix_restore.models import TableRepairResult


_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)


class TableMerger:
    def repair(self, markdown: str) -> TableRepairResult:
        if "<table" not in markdown.lower():
            return TableRepairResult(markdown=markdown, repaired_tags=0, warnings=[])

        repaired_tags = self._count_missing_closing_tags(markdown)
        soup = BeautifulSoup(markdown, "html.parser")
        warnings: list[str] = []
        self._merge_adjacent_duplicate_headers(soup, markdown)
        self._normalize_table_structure(soup)
        self._drop_orphan_cells(soup)
        self._restore_text_outside_tables(soup)
        body = soup.body
        if body is not None:
            rendered = "".join(str(child) for child in body.children)
        else:
            rendered = soup.decode(formatter="minimal")
        return TableRepairResult(markdown=rendered, repaired_tags=repaired_tags, warnings=warnings)

    def _count_missing_closing_tags(self, html: str) -> int:
        missing = 0
        lowered = html.lower()
        for tag in ("table", "tr", "td", "th"):
            opens = len(re.findall(fr"<{tag}\b", lowered))
            closes = lowered.count(f"</{tag}>")
            missing += max(0, opens - closes)
        return missing

    def _merge_adjacent_duplicate_headers(self, soup: BeautifulSoup, original: str) -> None:
        tables = soup.find_all("table")
        if len(tables) < 2:
            return
        adjacent_indexes = self._adjacent_table_indexes(original)
        for idx in sorted(adjacent_indexes, reverse=True):
            if idx <= 0 or idx >= len(tables):
                continue
            previous = tables[idx - 1]
            current = tables[idx]
            previous_rows = previous.find_all("tr")
            current_rows = current.find_all("tr")
            if not previous_rows or not current_rows:
                continue
            if self._row_key(previous_rows[0]) != self._row_key(current_rows[0]):
                continue
            for row in current_rows[1:]:
                previous.append(row.extract())
            current.decompose()

    def _adjacent_table_indexes(self, original: str) -> set[int]:
        matches = list(_TABLE_RE.finditer(original))
        adjacent: set[int] = set()
        for idx in range(1, len(matches)):
            between = original[matches[idx - 1].end() : matches[idx].start()]
            if between.strip() == "":
                adjacent.add(idx)
        return adjacent

    def _row_key(self, row) -> tuple[str, ...]:
        cells = row.find_all(["td", "th"])
        return tuple(cell.get_text(strip=True) for cell in cells)

    def _restore_text_outside_tables(self, soup: BeautifulSoup) -> None:
        for table in soup.find_all("table"):
            leading_nodes: list[NavigableString] = []
            trailing_nodes: list[NavigableString] = []

            while table.contents:
                first = table.contents[0]
                if not isinstance(first, NavigableString) or not first.strip():
                    break
                leading_nodes.append(first.extract())

            while table.contents:
                last = table.contents[-1]
                if not isinstance(last, NavigableString) or not last.strip():
                    break
                trailing_nodes.append(last.extract())

            for node in reversed(leading_nodes):
                table.insert_before(node)
            for node in trailing_nodes:
                table.insert_after(node)

    def _drop_orphan_cells(self, soup: BeautifulSoup) -> None:
        for cell in soup.find_all(["td", "th"]):
            parent = cell.find_parent("tr")
            if parent is None:
                cell.decompose()
        for row in soup.find_all("tr"):
            if row.find_parent("table") is None:
                row.decompose()

    def _normalize_table_structure(self, soup: BeautifulSoup) -> None:
        for table in soup.find_all("table"):
            loose_cells: list = []
            for child in list(table.children):
                if getattr(child, "name", None) in ("td", "th"):
                    loose_cells.append(child.extract())
            if loose_cells:
                wrapper = soup.new_tag("tr")
                for cell in loose_cells:
                    wrapper.append(cell)
                table.append(wrapper)
