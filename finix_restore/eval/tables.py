from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

_SEP_RE = re.compile(r"\|[:\- |]+\|")
_WS_RE = re.compile(r"\s+")


@dataclass
class TableNode:
    tag: str
    text: str = ""
    colspan: int = 1
    rowspan: int = 1
    children: list["TableNode"] = field(default_factory=list)


def _parse_span(value: object) -> int:
    try:
        span = int(str(value))
    except (TypeError, ValueError):
        return 1
    return max(1, span)


def _norm_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _table_to_node(table) -> TableNode:
    root = TableNode(tag="table")
    for tr in table.find_all("tr"):
        row = TableNode(tag="tr")
        for cell in tr.find_all(["td", "th"]):
            row.children.append(
                TableNode(
                    tag="td",
                    text=_norm_text(cell.get_text(" ", strip=True)),
                    colspan=_parse_span(cell.get("colspan")),
                    rowspan=_parse_span(cell.get("rowspan")),
                )
            )
        root.children.append(row)
    return root


def _parse_html_table(html: str) -> TableNode | None:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        return None
    return _table_to_node(table)


def _split_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _markdown_block_to_html(rows: list[str]) -> str:
    cells = ["".join(f"<td>{c}</td>" for c in _split_cells(r)) for r in rows]
    body = "".join(f"<tr>{c}</tr>" for c in cells)
    return f"<table>{body}</table>"


def _extract_markdown_tables(markdown: str) -> list[TableNode]:
    nodes: list[TableNode] = []
    lines = markdown.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        header = lines[i].strip()
        # Need at least a header row followed by a separator row.
        if (
            header.startswith("|")
            and header.endswith("|")
            and i + 1 < n
            and _SEP_RE.fullmatch(lines[i + 1].strip())
        ):
            block = [lines[i]]
            j = i + 2
            while j < n:
                data = lines[j].strip()
                if data.startswith("|") and data.endswith("|"):
                    block.append(lines[j])
                    j += 1
                else:
                    break
            node = _parse_html_table(_markdown_block_to_html(block))
            if node is not None:
                nodes.append(node)
            i = j
        else:
            i += 1
    return nodes


def extract_tables(markdown: str) -> list[TableNode]:
    nodes: list[TableNode] = []
    soup = BeautifulSoup(markdown, "lxml")
    for table in soup.find_all("table"):
        nodes.append(_table_to_node(table))
    nodes.extend(_extract_markdown_tables(markdown))
    return nodes
