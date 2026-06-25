from importlib import import_module
from pathlib import Path

import pytest

from finix_restore.models import Chunk, ChunkText


def _chunk_text(markdown: str, *, chunk_id: str, bbox: tuple[int, int, int, int]) -> ChunkText:
    return ChunkText(
        chunk=Chunk(
            chunk_id=chunk_id,
            file_name="long.png",
            image_path=Path("/tmp/long.jpg"),
            bbox=bbox,
            row=0,
            col=0,
            overlap={"left": 0, "right": 0, "top": 320, "bottom": 320},
            image_sha1="sha1",
        ),
        markdown=markdown,
        block_type="body",
        source="manual_fixture",
    )


def _load_long_merger_module():
    try:
        return import_module("finix_restore.long_merger")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing finix_restore.long_merger: {exc}")


def test_long_merger_merges_adjacent_table_fragments_with_same_header():
    long_merger = _load_long_merger_module()
    chunk_a = _chunk_text(
        "费率说明\n\n<table><tr><td>责任</td><td>说明</td></tr><tr><td>住院</td><td>给付</td></tr></table>",
        chunk_id="a",
        bbox=(0, 0, 100, 120),
    )
    chunk_b = _chunk_text(
        "<table><tr><td>责任</td><td>说明</td></tr><tr><td>门诊</td><td>给付</td></tr></table>\n\n续表后文",
        chunk_id="b",
        bbox=(0, 80, 100, 200),
    )

    result = long_merger.LongStripMerger().merge([chunk_a, chunk_b])

    assert result.markdown.count("<table") == 1
    assert "<td>住院</td><td>给付</td>" in result.markdown
    assert "<td>门诊</td><td>给付</td>" in result.markdown
    assert result.markdown.count("<td>责任</td><td>说明</td>") == 1
    assert result.merged_tables == 1


def test_long_merger_preserves_distinct_tables_when_headers_differ():
    long_merger = _load_long_merger_module()
    chunk_a = _chunk_text(
        "<table><tr><td>责任</td><td>说明</td></tr><tr><td>住院</td><td>给付</td></tr></table>",
        chunk_id="a",
        bbox=(0, 0, 100, 120),
    )
    chunk_b = _chunk_text(
        "<table><tr><td>项目</td><td>金额</td></tr><tr><td>门诊</td><td>2</td></tr></table>",
        chunk_id="b",
        bbox=(0, 80, 100, 200),
    )

    result = long_merger.LongStripMerger().merge([chunk_a, chunk_b])

    assert result.markdown.count("<table") == 2
    assert "long_table_alignment_uncertain" in result.warnings
    assert result.markdown.index("责任") < result.markdown.index("项目")
