from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


BlockType = Literal["title", "paragraph", "list_item", "table", "toc", "header_footer", "footnote"]


@dataclass(frozen=True)
class BlockSegment:
    block_type: BlockType
    text: str


class BlockSegmenter:
    def segment(self, markdown: str) -> list[BlockSegment]:
        stripped = markdown.strip()
        if not stripped:
            return []

        blocks = re.split(r"\n\s*\n+", stripped)
        segments: list[BlockSegment] = []
        for block in blocks:
            text = block.strip()
            if not text:
                continue
            segments.append(BlockSegment(block_type=self._classify(text), text=text))
        return segments

    def _classify(self, text: str) -> BlockType:
        lowered = text.lower()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if "<table" in lowered and "</tr>" in lowered:
            return "table"
        if self._looks_like_toc(lines):
            return "toc"
        if self._looks_like_header_footer(lines):
            return "header_footer"
        if lines and all(self._is_list_item(line) for line in lines):
            return "list_item"
        if lines and lines[0].startswith("#"):
            return "title"
        if lines and (lines[0].startswith("注：") or lines[0].startswith("注:")):
            return "footnote"
        return "paragraph"

    def _looks_like_toc(self, lines: list[str]) -> bool:
        if not lines:
            return False
        if any("目录" in line for line in lines[:3]):
            return True

        numbered = 0
        dotted = 0
        for line in lines[:8]:
            if re.match(r"^(\d+(\.\d+)*)\s+", line):
                numbered += 1
            if re.search(r"(\.{2,}|…{2,})\s*\d+\s*$", line):
                dotted += 1
        return len(lines) >= 3 and numbered >= 3 and dotted >= 2

    def _looks_like_header_footer(self, lines: list[str]) -> bool:
        if len(lines) != 1:
            return False
        line = lines[0]
        if re.match(r"^第\s*\d+\s*页(\s*共\s*\d+\s*页)?$", line):
            return True
        if len(line) <= 24 and ("版权所有" in line or "内部资料" in line):
            return True
        return False

    def _is_list_item(self, line: str) -> bool:
        return bool(re.match(r"^([-*+]|\d+[.)])\s+", line))
