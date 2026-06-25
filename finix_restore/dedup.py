from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Sequence

from finix_restore.block_segments import BlockSegment, BlockSegmenter
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
        self.segmenter = BlockSegmenter()

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
            removed_units = 0
            if self._chunks_overlap(previous.chunk, current.chunk):
                if self._can_dedup(previous, current):
                    current_text, removed_units = self._trim_line_overlap(previous.markdown, current_text)
                if removed_units == 0:
                    current_text, removed_units = self._trim_block_overlap(previous.markdown, current_text)
                if removed_units == 0 and self._can_dedup(previous, current):
                    overlap_len = self._find_prefix_suffix_overlap(merged, current_text, current.block_type)

            if overlap_len > 0:
                removed_ranges.append((current.chunk.chunk_id, 0, overlap_len))
                merged = self._append_after_overlap(merged, current_text[overlap_len:])
            elif removed_units > 0:
                removed_ranges.extend((current.chunk.chunk_id, 0, 0) for _ in range(removed_units))
                if current_text:
                    merged = self._append_paragraph(merged, current_text)
            elif self._should_continue_without_blank(merged):
                merged = merged.rstrip() + current_text.lstrip()
            else:
                merged = self._append_paragraph(merged, current_text)
            previous = current

        return MergeResult(markdown=merged.strip() + ("\n" if merged.strip() else ""), removed_ranges=removed_ranges, warnings=warnings)

    def _can_dedup(self, previous: ChunkText, current: ChunkText) -> bool:
        previous_block_type = self._effective_block_type(previous)
        current_block_type = self._effective_block_type(current)
        if previous_block_type in _PROTECTED_BLOCKS or current_block_type in _PROTECTED_BLOCKS:
            return False
        return self._chunks_overlap(previous.chunk, current.chunk)

    def _effective_block_type(self, chunk: ChunkText) -> str:
        if chunk.block_type in _PROTECTED_BLOCKS:
            return chunk.block_type
        for segment in self.segmenter.segment(chunk.markdown):
            if segment.block_type in _PROTECTED_BLOCKS:
                return segment.block_type
        return chunk.block_type

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

    def _trim_line_overlap(self, previous_text: str, current_text: str) -> tuple[str, int]:
        previous_lines = [line for line in previous_text.splitlines() if line.strip()]
        current_lines = [line for line in current_text.splitlines() if line.strip()]
        if not previous_lines or not current_lines:
            return current_text, 0

        max_match = min(8, len(previous_lines), len(current_lines))
        for size in range(max_match, 0, -1):
            tail = previous_lines[-size:]
            head = current_lines[:size]
            if all(self._blocks_match(left, right) for left, right in zip(tail, head)):
                return self._remove_nonempty_prefix_lines(current_text, size), size
        return current_text, 0

    def _remove_nonempty_prefix_lines(self, text: str, count: int) -> str:
        kept: list[str] = []
        removed = 0
        for line in text.splitlines():
            if removed < count and line.strip():
                removed += 1
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _trim_block_overlap(self, previous_text: str, current_text: str) -> tuple[str, int]:
        previous_blocks = self._logical_blocks(previous_text)[-3:]
        current_blocks = self._logical_blocks(current_text)
        if not previous_blocks or not current_blocks:
            return current_text, 0

        previous_candidates = [block for block in previous_blocks if block.block_type not in _PROTECTED_BLOCKS]
        current_candidates = [block for block in current_blocks[:3] if block.block_type not in _PROTECTED_BLOCKS]
        max_match = min(len(previous_candidates), len(current_candidates))
        if max_match == 0:
            return current_text, 0

        for size in range(max_match, 0, -1):
            tail = previous_candidates[-size:]
            head = current_candidates[:size]
            if all(self._blocks_match(left.text, right.text) for left, right in zip(tail, head)):
                rebuilt = self._rebuild_after_removing_nonprotected_prefix(current_blocks, size)
                return rebuilt, size
        return current_text, 0

    def _rebuild_after_removing_nonprotected_prefix(self, blocks, count: int) -> str:
        remaining: list[str] = []
        removed = 0
        for block in blocks:
            if removed < count and block.block_type not in _PROTECTED_BLOCKS:
                removed += 1
                continue
            remaining.append(block.text)
        return "\n\n".join(part for part in remaining if part.strip())

    def _blocks_match(self, left: str, right: str) -> bool:
        left_norm = self._normalize_block_text(left)
        right_norm = self._normalize_block_text(right)
        if not left_norm or not right_norm:
            return False
        if left_norm == right_norm:
            return True
        return SequenceMatcher(None, left_norm, right_norm).ratio() >= self.similarity_threshold

    def _normalize_block_text(self, text: str) -> str:
        normalized = re.sub(r"<[^>]+>", "", text)
        normalized = re.sub(r"^#{1,6}\s*", "", normalized.strip())
        normalized = normalized.replace("（", "(").replace("）", ")")
        return re.sub(r"\s+", "", normalized).lower()

    def _logical_blocks(self, markdown: str) -> list[BlockSegment]:
        logical: list[BlockSegment] = []
        for block in self.segmenter.segment(markdown):
            lines = [line.strip() for line in block.text.splitlines() if line.strip()]
            if block.block_type == "title" and len(lines) > 1:
                logical.append(BlockSegment(block_type="title", text=lines[0]))
                remainder = "\n".join(lines[1:]).strip()
                if remainder:
                    logical.append(BlockSegment(block_type="paragraph", text=remainder))
                continue
            logical.append(block)
        return logical

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
