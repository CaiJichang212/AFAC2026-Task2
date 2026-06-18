from __future__ import annotations

from difflib import SequenceMatcher
from typing import Sequence

from finix_restore.models import Chunk, ChunkText, MergeResult


_PROTECTED_BLOCKS = {"toc", "table", "header_footer"}


class DedupMerger:
    def __init__(
        self,
        window_chars_long: int = 1200,
        window_chars_table: int = 600,
        similarity_threshold: float = 0.88,
    ) -> None:
        self.window_chars_long = window_chars_long
        self.window_chars_table = window_chars_table
        self.similarity_threshold = similarity_threshold

    def merge(self, ordered_chunks: Sequence[ChunkText]) -> MergeResult:
        if not ordered_chunks:
            return MergeResult(markdown="", removed_ranges=[], warnings=[])

        merged = ordered_chunks[0].markdown.rstrip()
        previous = ordered_chunks[0]
        removed_ranges: list[tuple[str, int, int]] = []
        warnings: list[str] = []

        for current in ordered_chunks[1:]:
            current_text = current.markdown.strip()
            overlap_len = 0
            if self._can_dedup(previous, current):
                overlap_len = self._find_prefix_suffix_overlap(merged, current_text, current.block_type)

            if overlap_len > 0:
                removed_ranges.append((current.chunk.chunk_id, 0, overlap_len))
                merged = self._append_after_overlap(merged, current_text[overlap_len:])
            elif self._should_continue_without_blank(merged):
                merged = merged.rstrip() + current_text.lstrip()
            else:
                merged = self._append_paragraph(merged, current_text)
            previous = current

        return MergeResult(markdown=merged.strip() + ("\n" if merged.strip() else ""), removed_ranges=removed_ranges, warnings=warnings)

    def _can_dedup(self, previous: ChunkText, current: ChunkText) -> bool:
        if previous.block_type in _PROTECTED_BLOCKS or current.block_type in _PROTECTED_BLOCKS:
            return False
        return self._chunks_overlap(previous.chunk, current.chunk)

    def _chunks_overlap(self, previous: Chunk, current: Chunk) -> bool:
        has_declared_overlap = any(int(value) > 0 for value in current.overlap.values()) or any(
            int(value) > 0 for value in previous.overlap.values()
        )
        if not has_declared_overlap:
            return False
        ax0, ay0, ax1, ay1 = previous.bbox
        bx0, by0, bx1, by1 = current.bbox
        x_overlap = min(ax1, bx1) - max(ax0, bx0)
        y_overlap = min(ay1, by1) - max(ay0, by0)
        return x_overlap > 0 and y_overlap > 0

    def _find_prefix_suffix_overlap(self, previous_text: str, current_text: str, block_type: str) -> int:
        window = self.window_chars_table if block_type == "table" else self.window_chars_long
        tail = previous_text[-window:]
        head = current_text[:window]
        max_len = min(len(tail), len(head))
        if max_len < 20:
            return 0

        for size in range(max_len, 19, -1):
            if tail[-size:] == head[:size]:
                return size

        for size in range(max_len, 39, -25):
            ratio = SequenceMatcher(None, tail[-size:], head[:size]).ratio()
            if ratio >= self.similarity_threshold:
                return size
        return 0

    def _append_after_overlap(self, merged: str, suffix: str) -> str:
        if not suffix:
            return merged.rstrip()
        if suffix.startswith("\n"):
            return merged.rstrip() + suffix
        if self._should_continue_without_blank(merged):
            return merged.rstrip() + suffix.lstrip()
        return self._append_paragraph(merged, suffix)

    def _append_paragraph(self, merged: str, text: str) -> str:
        if not merged:
            return text.lstrip()
        if not text:
            return merged.rstrip()
        return merged.rstrip() + "\n\n" + text.lstrip()

    def _should_continue_without_blank(self, text: str) -> bool:
        tail = text.rstrip()
        if not tail:
            return False
        if tail.count("（") > tail.count("）") or tail.count("(") > tail.count(")"):
            return True
        if tail.count("<td") > tail.count("</td>"):
            return True
        if tail.count("<tr") > tail.count("</tr>"):
            return True
        return tail[-1] in "，、：；-/"
