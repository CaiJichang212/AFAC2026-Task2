from importlib import import_module
from pathlib import Path

import pytest

from finix_restore.eval.tables import extract_tables
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


def test_long_merger_collapses_repeated_short_blocks_across_chunks():
    long_merger = _load_long_merger_module()
    chunk_a = _chunk_text(
        "受益人与被保险人在同一事件中死亡，且不能确定死亡先后顺序的。\n\n"
        "### （二）意外残疾保险金受益人",
        chunk_id="a",
        bbox=(0, 0, 100, 80),
    )
    chunk_b = _chunk_text(
        "### （二）意外残疾保险金受益人\n\n"
        "除另有约定外，本合同的意外残疾保险金的受益人为被保险人本人。",
        chunk_id="b",
        bbox=(0, 60, 100, 160),
    )

    result = long_merger.LongStripMerger().merge([chunk_a, chunk_b])

    assert result.markdown.count("### （二）意外残疾保险金受益人") == 1
    assert "除另有约定外" in result.markdown
    assert "受益人与被保险人在同一事件中死亡" in result.markdown


def test_long_merger_does_not_collapse_long_or_table_blocks():
    long_merger = _load_long_merger_module()
    long_paragraph = (
        "长正文示例：" + "段落内容" * 30 + "。"
    )
    chunk_a = _chunk_text(
        long_paragraph + "\n\n中间段。",
        chunk_id="a",
        bbox=(0, 0, 100, 80),
    )
    chunk_b = _chunk_text(
        "中间段。\n\n" + long_paragraph,
        chunk_id="b",
        bbox=(0, 200, 100, 280),
    )

    result = long_merger.LongStripMerger().merge([chunk_a, chunk_b])

    # bbox 不重叠 -> 上游 dedup 不会触发；超长段落不应被新去重步骤压缩。
    assert result.markdown.count(long_paragraph) >= 2
    # 中间的短重复段会被新去重压缩，只保留一份。
    assert result.markdown.count("中间段。") == 1


def test_long_merger_stitches_split_four_column_section_table():
    long_merger = _load_long_merger_module()
    chunk_a = _chunk_text(
        "甲状腺癌分期\n\n"
        "## 乳头状或滤泡状癌（分化型）\n\n"
        "### 年龄&lt;55岁\n\n"
        "<table>"
        "<tr><td></td><td>T</td><td>N</td><td>M</td></tr>"
        "<tr><td>I期</td><td>任何</td><td>任何</td><td>0</td></tr>"
        "<tr><td>II期</td><td>任何</td><td>任何</td><td>1</td></tr>"
        "</table>\n\n"
        "### 年龄≥55岁\n\n"
        "<table>"
        "<tr><td rowspan=\"2\">I期</td><td>1</td><td>0/x</td><td>0</td></tr>"
        "<tr><td>2</td><td>0/x</td><td>0</td></tr>"
        "</table>",
        chunk_id="a",
        bbox=(0, 0, 100, 120),
    )
    chunk_b = _chunk_text(
        "髓样癌（所有年龄组）\n\n"
        "<table>"
        "<tr><td>I期</td><td>1</td><td>0</td><td>0</td></tr>"
        "<tr><td>II期</td><td>2~3</td><td>0</td><td>0</td></tr>"
        "</table>\n\n"
        "未分化癌（所有年龄组）\n\n"
        "<table>"
        "<tr><td>IVA期</td><td>1~3a</td><td>0/x</td><td>0</td></tr>"
        "</table>",
        chunk_id="b",
        bbox=(0, 80, 100, 200),
    )

    result = long_merger.LongStripMerger().merge([chunk_a, chunk_b])

    assert result.markdown.count("<table") == 1
    assert result.merged_tables == 3
    assert "long_table_alignment_uncertain" not in result.warnings
    tables = extract_tables(result.markdown)
    assert len(tables) == 1
    assert [cell.text for cell in tables[0].children[0].children] == ["乳头状或滤泡状癌（分化型）"]
    assert tables[0].children[0].children[0].colspan == 4
    assert any(row.children[0].text == "髓样癌（所有年龄组）" for row in tables[0].children)
    assert any(cell.rowspan == 2 for row in tables[0].children for cell in row.children)

