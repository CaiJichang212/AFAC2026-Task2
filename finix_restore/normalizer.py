from __future__ import annotations

import re

from finix_restore.models import ChunkText


# 仅当井号后紧跟“非井号、非空格”字符时补空格，避免把 "## 1." 这类已带空格的
# 多级标题误拆成 "# # 1."。
_HEADING_WITHOUT_SPACE = re.compile(r"^(#{1,6})(?=[^#\s])")
# 形如 "# # 1. 标题"、"## # (1) 标题" 的坏标题：井号前缀 + 多余内嵌 "#" + 正文。
# 历史上由旧的补空格正则回溯产生，也可能来自 VLM 偶发输出。
_DOUBLED_HASH_HEADING = re.compile(r"^(#{1,6})\s+#\s+(\S.*)$")
_API_ERROR_PATTERNS = (
    "empty response",
    "api error",
    "request failed",
    "server error",
)
# VLM 经常把整段输出用 ```markdown / ```html / ``` 代码围栏包裹。围栏会污染
# 文本编辑距离，并在多切片拼接后嵌入表格行中间破坏 HTML/TEDS 结构，必须剥离。
# 只剥“独占一行”的围栏标记，避免误删正文里出现的连续反引号代码示例。
_CODE_FENCE_LINE = re.compile(r"^\s*`{3,}\s*[a-zA-Z0-9_-]*\s*$")


class MarkdownNormalizer:
    def normalize(self, markdown: str) -> str:
        text = markdown.replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = []
        for line in text.split("\n"):
            stripped_line = line.rstrip()
            if self._is_obvious_api_error(stripped_line):
                continue
            if _CODE_FENCE_LINE.match(stripped_line):
                continue
            stripped_line = self._fix_doubled_hash_heading(stripped_line)
            stripped_line = _HEADING_WITHOUT_SPACE.sub(r"\1 ", stripped_line)
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

    def _fix_doubled_hash_heading(self, line: str) -> str:
        match = _DOUBLED_HASH_HEADING.match(line)
        if match is None:
            return line
        prefix_level = len(match.group(1))
        content = match.group(2).strip()
        level = self._heading_level_for(content, prefix_level)
        return f"{'#' * level} {content}"

    def _heading_level_for(self, content: str, prefix_level: int) -> int:
        # 依据条款编号深度推断层级，尽量贴近 GT 结构：
        #   "1." -> ##(2)，"1.1" -> ###(3)，"1.1.1" -> ####(4)；
        #   "(1)"/"（1）"/圆圈数字等枚举项 -> ###(3)；
        #   无编号时保留原井号前缀深度（仅折叠多余的 "#"）。
        numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\b", content)
        if numbered:
            depth = numbered.group(1).count(".") + 1
            return min(6, depth + 1)
        if re.match(r"^[（(]\s*\d+\s*[)）]", content) or re.match(r"^[①-⑳]", content):
            return 3
        return min(6, max(1, prefix_level))

    def _is_obvious_api_error(self, line: str) -> bool:
        lowered = line.lower()
        return any(pattern in lowered for pattern in _API_ERROR_PATTERNS)
