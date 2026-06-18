from __future__ import annotations

import re

from finix_restore.models import ChunkText


_HEADING_WITHOUT_SPACE = re.compile(r"^(#{1,6})(?!\s)(.+)$")
_API_ERROR_PATTERNS = (
    "empty response",
    "api error",
    "request failed",
    "server error",
)


class MarkdownNormalizer:
    def normalize(self, markdown: str) -> str:
        text = markdown.replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = []
        for line in text.split("\n"):
            stripped_line = line.rstrip()
            if self._is_obvious_api_error(stripped_line):
                continue
            stripped_line = _HEADING_WITHOUT_SPACE.sub(r"\1 \2", stripped_line)
            lines.append(stripped_line)
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def normalize_chunk(self, chunk_text: ChunkText) -> ChunkText:
        return ChunkText(
            chunk=chunk_text.chunk,
            markdown=self.normalize(chunk_text.markdown),
            block_type=chunk_text.block_type,
            source=chunk_text.source,
        )

    def batch(self, chunks: list[ChunkText]) -> list[ChunkText]:
        return [self.normalize_chunk(chunk) for chunk in chunks]

    def _is_obvious_api_error(self, line: str) -> bool:
        lowered = line.lower()
        return any(pattern in lowered for pattern in _API_ERROR_PATTERNS)
