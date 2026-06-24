from finix_restore.block_segments import BlockSegmenter


def test_block_segmenter_splits_title_and_paragraph():
    segments = BlockSegmenter().segment("# 1 总则\n\n正文")

    assert [segment.block_type for segment in segments] == ["title", "paragraph"]


def test_block_segmenter_classifies_toc_list_table_and_header_footer():
    markdown = (
        "1 总则 ........ 1\n"
        "2 保险责任 ........ 2\n"
        "3 责任免除 ........ 3\n\n"
        "- 投保条件\n\n"
        "<table><tr><td>A</td></tr></table>\n\n"
        "第1页 共2页"
    )

    segments = BlockSegmenter().segment(markdown)

    assert [segment.block_type for segment in segments] == [
        "toc",
        "list_item",
        "table",
        "header_footer",
    ]
