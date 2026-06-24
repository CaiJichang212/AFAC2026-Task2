from pathlib import Path

from finix_restore.models import Chunk, ChunkText
from finix_restore.table_assembler import TableRowAssembler


def _chunk_text(
    markdown: str,
    *,
    row_band: int,
    col_band: int,
    chunk_id: str,
    variant_kind: str = "table_crop",
    anchor_bbox: tuple[int, int, int, int] | None = None,
) -> ChunkText:
    return ChunkText(
        chunk=Chunk(
            chunk_id=chunk_id,
            file_name="table.png",
            image_path=Path("/tmp/table.jpg"),
            bbox=(0, 0, 100, 100),
            row=row_band,
            col=col_band,
            overlap={"left": 0, "right": 0, "top": 0, "bottom": 0},
            image_sha1="sha1",
            table_group_id="table",
            row_band=row_band,
            col_band=col_band,
            base_bbox=(0, 0, 100, 100),
            overlap_bbox=(0, 0, 100, 100),
            requires_row_assembly=True,
            variant_kind=variant_kind,
            anchor_bbox=anchor_bbox,
        ),
        markdown=markdown,
        block_type="table",
        source="manual_fixture",
    )


def test_table_row_assembler_horizontally_stitches_same_row_band():
    left = _chunk_text(
        "<table><tr><td>终身</td><td>1</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="left",
    )
    right = _chunk_text(
        "<table><tr><td>男</td><td>2176</td></tr></table>",
        row_band=0,
        col_band=1,
        chunk_id="right",
    )

    result = TableRowAssembler().assemble([left, right])

    assert "<td>终身</td><td>1</td><td>男</td><td>2176</td>" in result.markdown
    assert result.warnings == ()
    assert result.assembled_tables == 1


def test_table_row_assembler_vertically_merges_duplicate_headers():
    top = _chunk_text(
        "<table><tr><td>项目</td><td>金额</td></tr><tr><td>A</td><td>1</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="top",
    )
    bottom = _chunk_text(
        "<table><tr><td>项目</td><td>金额</td></tr><tr><td>B</td><td>2</td></tr></table>",
        row_band=1,
        col_band=0,
        chunk_id="bottom",
    )

    result = TableRowAssembler().assemble([top, bottom])

    assert result.markdown.count("<td>项目</td><td>金额</td>") == 1
    assert "<td>A</td><td>1</td>" in result.markdown
    assert "<td>B</td><td>2</td>" in result.markdown
    assert result.assembled_tables == 1


def test_table_row_assembler_keeps_original_order_when_alignment_is_uncertain():
    left = _chunk_text(
        "<table><tr><td>终身</td><td>1</td></tr><tr><td>定期</td><td>2</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="left-uncertain",
    )
    right = _chunk_text(
        "<table><tr><td>男</td><td>2176</td></tr></table>",
        row_band=0,
        col_band=1,
        chunk_id="right-uncertain",
    )

    result = TableRowAssembler().assemble([left, right])

    assert "row_alignment_uncertain" in result.warnings
    assert "<td>终身</td><td>1</td>" in result.markdown
    assert "<td>定期</td><td>2</td>" in result.markdown
    assert "<td>男</td><td>2176</td>" in result.markdown


def test_table_row_assembler_merges_vertical_bands_with_text_and_overlap_dedup():
    top = _chunk_text(
        "费率表A\n<table>"
        "<tr><th>项目</th><th>金额</th></tr>"
        "<tr><td>A</td><td>1</td></tr>"
        "<tr><td>B</td><td>2</td></tr>"
        "</table>",
        row_band=0,
        col_band=0,
        chunk_id="band-top",
    )
    bottom = _chunk_text(
        "费率表A\n<table>"
        "<tr><th>项目</th><th>金额</th></tr>"
        "<tr><td>B</td><td>2</td></tr>"
        "<tr><td>C</td><td>3</td></tr>"
        "</table>",
        row_band=1,
        col_band=0,
        chunk_id="band-bottom",
    )

    result = TableRowAssembler().assemble([top, bottom])

    assert result.markdown.count("费率表A") == 1
    assert result.markdown.count("<th>项目</th><th>金额</th>") == 1
    assert result.markdown.count("<td>B</td><td>2</td>") == 1
    assert "<td>C</td><td>3</td>" in result.markdown
    assert result.assembled_tables == 1


def test_table_row_assembler_aligns_horizontal_chunks_by_anchor_column():
    left = _chunk_text(
        "<table>"
        "<tr><th>年龄</th><th>男</th><th>女</th></tr>"
        "<tr><td>18岁</td><td>100</td><td>120</td></tr>"
        "<tr><td>19岁</td><td>130</td><td>150</td></tr>"
        "</table>",
        row_band=0,
        col_band=0,
        chunk_id="anchor-left",
        anchor_bbox=(0, 0, 40, 100),
    )
    right = _chunk_text(
        "<table>"
        "<tr><th>年龄</th><th>保额</th><th>费率</th></tr>"
        "<tr><td>18岁</td><td>10万</td><td>2176</td></tr>"
        "<tr><td>19岁</td><td>10万</td><td>2388</td></tr>"
        "</table>",
        row_band=0,
        col_band=1,
        chunk_id="anchor-right",
        anchor_bbox=(0, 0, 40, 100),
    )

    result = TableRowAssembler().assemble([left, right])

    assert "row_alignment_uncertain" not in result.warnings
    assert "<th>年龄</th><th>男</th><th>女</th><th>保额</th><th>费率</th>" in result.markdown
    assert result.markdown.count("<td>18岁</td>") == 1
    assert "<td>18岁</td><td>100</td><td>120</td><td>10万</td><td>2176</td>" in result.markdown
