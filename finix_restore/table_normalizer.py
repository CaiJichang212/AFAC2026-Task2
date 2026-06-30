from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag


_FULLWIDTH_MAP = {
    0xFF08: "(",  # （
    0xFF09: ")",  # ）
    0xFF0C: ",",  # ，
    0xFF0E: ".",  # ．
    0x3002: ".",  # 。
    0xFF1A: ":",  # ：
    0xFF1B: ";",  # ；
    0xFF05: "%",  # ％
}
_PAREN_NEGATIVE_RE = re.compile(r"\(\s*([\d.,]+)\s*\)")
_TRAILING_ZERO_RE = re.compile(r"(\d)\.0+(?!\d)")
_PERCENT_SPACE_RE = re.compile(r"\s+%")
_THOUSAND_GROUP_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _normalize_cell_text(text: str) -> str:
    if not text:
        return text
    out_chars = []
    for ch in text:
        code = ord(ch)
        if code in _FULLWIDTH_MAP:
            out_chars.append(_FULLWIDTH_MAP[code])
            continue
        out_chars.append(ch)
    result = "".join(out_chars)
    result = _PAREN_NEGATIVE_RE.sub(lambda m: "-" + m.group(1), result)
    while _THOUSAND_GROUP_RE.search(result):
        result = _THOUSAND_GROUP_RE.sub("", result)
    result = _TRAILING_ZERO_RE.sub(r"\1", result)
    result = _PERCENT_SPACE_RE.sub("%", result)
    return result


class TableNormalizer:
    def normalize(self, markdown: str) -> str:
        if "<table" not in markdown.lower():
            return markdown
        soup = BeautifulSoup(markdown, "html.parser")
        for cell in soup.find_all(["td", "th"]):
            self._normalize_cell_node(cell)
        body = soup.body
        if body is not None:
            return "".join(str(child) for child in body.children)
        return soup.decode(formatter="minimal")

    def _normalize_cell_node(self, cell: Tag) -> None:
        for descendant in list(cell.descendants):
            if isinstance(descendant, NavigableString) and descendant.strip():
                normalized = _normalize_cell_text(str(descendant))
                if normalized != str(descendant):
                    descendant.replace_with(NavigableString(normalized))
            elif isinstance(descendant, Tag) and descendant.name in ("td", "th"):
                continue
