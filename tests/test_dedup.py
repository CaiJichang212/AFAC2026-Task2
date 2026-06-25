from pathlib import Path

from finix_restore.models import Chunk, ChunkText


def _chunk(chunk_id: str, bbox, overlap) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_name="doc.png",
        image_path=Path(f"/tmp/{chunk_id}.jpg"),
        bbox=bbox,
        row=0,
        col=0,
        overlap=overlap,
        image_sha1="sha",
    )


def _chunk_text(chunk_id: str, markdown: str, bbox, overlap, block_type="body") -> ChunkText:
    return ChunkText(
        chunk=_chunk(chunk_id, bbox, overlap),
        markdown=markdown,
        block_type=block_type,
        source="manual_fixture",
    )


def test_overlap_prefix_suffix_duplicate_is_removed_once():
    from finix_restore.dedup import DedupMerger

    repeated = "重复内容" * 30
    first = _chunk_text("a", f"前文\n{repeated}", (0, 0, 100, 100), {"bottom": 20})
    second = _chunk_text("b", f"{repeated}\n后文", (0, 80, 100, 180), {"top": 20})

    merged = DedupMerger().merge([first, second])

    assert merged.markdown.count(repeated) == 1
    assert "前文" in merged.markdown
    assert "后文" in merged.markdown
    assert merged.removed_ranges


def test_toc_and_body_title_duplicates_are_preserved():
    from finix_restore.dedup import DedupMerger

    toc = _chunk_text("toc", "# 条款目录\n# 1 总则", (0, 0, 100, 100), {"bottom": 20}, block_type="toc")
    body = _chunk_text("body", "# 1 总则\n正文", (0, 80, 100, 180), {"top": 20}, block_type="body")

    merged = DedupMerger().merge([toc, body])

    assert merged.markdown.count("# 1 总则") == 2


def test_unclosed_sentence_continues_without_blank_paragraph():
    from finix_restore.dedup import DedupMerger

    first = _chunk_text("a", "保险责任（包括", (0, 0, 100, 100), {"bottom": 20})
    second = _chunk_text("b", "住院医疗）和门诊责任。", (0, 80, 100, 180), {"top": 20})

    merged = DedupMerger().merge([first, second])

    assert "保险责任（包括住院医疗）和门诊责任。" in merged.markdown
    assert "包括\n\n住院" not in merged.markdown


def test_block_level_overlap_removes_fuzzy_duplicate_heading_once():
    from finix_restore.dedup import DedupMerger

    first = _chunk_text("a", "## 2.3 等待期", (0, 0, 100, 100), {"bottom": 20})
    second = _chunk_text("b", "## 2.3等待期\n正文", (0, 80, 100, 180), {"top": 20})

    merged = DedupMerger().merge([first, second])

    assert merged.markdown.count("等待期") == 1
    assert "正文" in merged.markdown


def test_line_level_overlap_removes_heading_and_body_duplicate():
    from finix_restore.dedup import DedupMerger

    first = _chunk_text(
        "a",
        "前文\n\n受益人与被保险人在同一事件中死亡，且不能确定死亡先后顺序的，推定受益人死亡在先。\n\n### （二）意外残疾保险金受益人",
        (0, 0, 100, 120),
        {"bottom": 20},
    )
    second = _chunk_text(
        "b",
        "受益人与被保险人在同一事件中死亡，且不能确定死亡先后顺序的，推定受益人死亡在先。\n\n## (二) 意外残疾保险金受益人\n\n除另有约定外，本合同的意外残疾保险金的受益人为被保险人本人。",
        (0, 100, 100, 220),
        {"top": 20},
    )

    merged = DedupMerger().merge([first, second])

    assert merged.markdown.count("受益人与被保险人") == 1
    assert merged.markdown.count("意外残疾保险金受益人") == 1
    assert "除另有约定外" in merged.markdown


def test_block_level_overlap_keeps_table_fragments_for_long_merger():
    from finix_restore.dedup import DedupMerger

    first = _chunk_text(
        "a",
        "等待期说明\n\n<table><tr><td>A</td></tr></table>",
        (0, 0, 100, 120),
        {"bottom": 20},
    )
    second = _chunk_text(
        "b",
        "等待期说明\n\n<table><tr><td>B</td></tr></table>",
        (0, 100, 100, 220),
        {"top": 20},
    )

    merged = DedupMerger().merge([first, second])

    assert merged.markdown.count("等待期说明") == 1
    assert "<td>A</td>" in merged.markdown
    assert "<td>B</td>" in merged.markdown
    assert merged.markdown.count("<table") == 2
