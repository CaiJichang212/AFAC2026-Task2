from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from finix_restore.models import ChunkText, DocType


class ReadingOrderResolver:
    def resolve(self, chunks: Sequence[ChunkText], doc_type: DocType = "unknown") -> list[ChunkText]:
        candidates = [chunk for chunk in chunks if not self._is_reference_chunk(chunk, doc_type)]
        if doc_type == "table_page":
            ordered = sorted(candidates, key=lambda item: (item.chunk.row, item.chunk.col, item.chunk.bbox[1], item.chunk.bbox[0]))
        else:
            ordered = sorted(candidates, key=lambda item: (item.chunk.bbox[1], item.chunk.bbox[0]))
        return [self._mark_structure(chunk) for chunk in ordered]

    def sort(self, chunks: Sequence[ChunkText], doc_type: DocType = "unknown") -> list[ChunkText]:
        return self.resolve(chunks, doc_type=doc_type)

    def _is_reference_chunk(self, chunk: ChunkText, doc_type: DocType) -> bool:
        return doc_type == "table_page" and (chunk.chunk.row < 0 or chunk.chunk.col < 0)

    def _mark_structure(self, chunk: ChunkText) -> ChunkText:
        if self._looks_like_toc(chunk.markdown):
            return replace(chunk, block_type="toc")
        return chunk

    def _looks_like_toc(self, markdown: str) -> bool:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        if not lines:
            return False
        first = lines[0].lstrip("# ").strip()
        if "目录" in first:
            return True
        if len(lines) < 3:
            return False
        numbered = 0
        for line in lines[:8]:
            if line[0].isdigit() and ("." in line[:8] or " " in line[:8]):
                numbered += 1
        return numbered >= 3 and any("目录" in line for line in lines[:3])
