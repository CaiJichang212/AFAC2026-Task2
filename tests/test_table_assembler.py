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

    # P2.2: "项目/金额"被自动检测为表头, 渲染为 <th>。验证表头去重仍生效。
    assert result.markdown.count("项目</th><th>金额</th>") == 1
    assert "<td>A</td><td>1</td>" in result.markdown
    assert "<td>B</td><td>2</td>" in result.markdown
    assert result.assembled_tables == 1


def test_table_row_assembler_stitches_uneven_rows_by_common_count():
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

    assert "<td>终身</td><td>1</td><td>男</td><td>2176</td>" in result.markdown
    assert "<td>定期</td><td>2</td>" in result.markdown
    assert result.assembled_tables == 1


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


def test_table_row_assembler_concatenates_multi_table_chunk():
    chunk = _chunk_text(
        "<table><tr><td>A</td><td>1</td></tr></table>"
        "<table><tr><td>B</td><td>2</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="multi-left",
    )
    other = _chunk_text(
        "<table><tr><td>C</td><td>3</td></tr></table>",
        row_band=0,
        col_band=1,
        chunk_id="multi-right",
    )

    result = TableRowAssembler().assemble([chunk, other])

    assert "<td>A</td><td>1</td>" in result.markdown
    assert "<td>B</td><td>2</td>" in result.markdown
    assert "<td>C</td><td>3</td>" in result.markdown
    # 多表串接为单表, 不再散落多个 <table>
    # P2.1: table 标签现在带 border 属性, 统计开始标签数验证单表。
    assert result.markdown.count("<table") == 1


def test_table_row_assembler_fallback_groups_rows_by_column_count():
    # anchor 对齐失败 (首列完全不同) -> 走 fallback 按列数分组
    left = _chunk_text(
        "<table><tr><td>甲</td><td>1</td></tr><tr><td>乙</td><td>2</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="fb-left",
        anchor_bbox=(0, 0, 40, 100),
    )
    right = _chunk_text(
        "<table><tr><td>完全不同甲</td><td>9</td></tr><tr><td>完全不同乙</td><td>8</td></tr></table>",
        row_band=0,
        col_band=1,
        chunk_id="fb-right",
        anchor_bbox=(0, 0, 40, 100),
    )

    result = TableRowAssembler().assemble([left, right])

    # fallback 后仍是单表结构 (两块列数相同, 归为一组), 不输出原始 markdown 多表并列
    # P2.1/P0.3: table 标签带属性, fallback 强制单表包裹。
    assert result.markdown.count("<table") == 1
    assert "<td>甲</td><td>1</td>" in result.markdown
    assert "<td>完全不同甲</td><td>9</td>" in result.markdown


def test_table_row_assembler_ignores_no_table_band_when_combining_tables():
    top = _chunk_text(
        "<table><tr><td>项目</td><td>金额</td></tr><tr><td>A</td><td>1</td></tr></table>",
        row_band=0,
        col_band=0,
        chunk_id="top-table",
    )
    text_only = _chunk_text(
        "识别出的说明文字, 没有表格标签",
        row_band=1,
        col_band=0,
        chunk_id="middle-text",
    )
    bottom = _chunk_text(
        "<table><tr><td>项目</td><td>金额</td></tr><tr><td>B</td><td>2</td></tr></table>",
        row_band=2,
        col_band=0,
        chunk_id="bottom-table",
    )

    result = TableRowAssembler().assemble([top, text_only, bottom])

    # P2.1: table 标签带 border 属性, 统计开始标签数验证单表。
    assert result.markdown.count("<table") == 1
    assert "识别出的说明文字" in result.markdown
    assert "<td>A</td><td>1</td>" in result.markdown
    assert "<td>B</td><td>2</td>" in result.markdown
    assert result.assembled_tables == 1


def test_table_row_assembler_renders_table_with_border_attributes():
    # P2.1: 输出的 <table> 应带 border/cellpadding/cellspacing 属性, 对齐 GT。
    chunk = _chunk_text(
        "<table><tr><td>A</td><td>1</td></tr></table>",
        row_band=0, col_band=0, chunk_id="border-test",
    )
    result = TableRowAssembler().assemble([chunk])
    assert 'border="1"' in result.markdown
    assert 'cellpadding="8"' in result.markdown
    assert 'cellspacing="0"' in result.markdown


def test_table_row_assembler_aligns_uneven_rows_left_longer():
    # P0.2: 左块行数 > 右块行数时, 左块多出的行应保留, 不丢失尾部数据。
    left = _chunk_text(
        "<table>"
        "<tr><td>18</td><td>100</td></tr>"
        "<tr><td>19</td><td>130</td></tr>"
        "</table>",
        row_band=0, col_band=0, chunk_id="long-left",
        anchor_bbox=(0, 0, 40, 100),
    )
    right = _chunk_text(
        "<table><tr><td>18</td><td>200</td></tr></table>",
        row_band=0, col_band=1, chunk_id="short-right",
        anchor_bbox=(0, 0, 40, 100),
    )
    result = TableRowAssembler().assemble([left, right])
    # 第 1 行横向缝合
    assert "<td>18</td><td>100</td><td>200</td>" in result.markdown
    # 左块第 2 行保留 (不丢失)
    assert "<td>19</td><td>130</td>" in result.markdown
    assert result.assembled_tables == 1


def test_table_row_assembler_aligns_uneven_rows_right_longer():
    # P0.2: 右块行数 > 左块行数时, 右块多出的行应追加, 不丢失尾部数据。
    left = _chunk_text(
        "<table><tr><td>18</td><td>100</td></tr></table>",
        row_band=0, col_band=0, chunk_id="short-left",
        anchor_bbox=(0, 0, 40, 100),
    )
    right = _chunk_text(
        "<table>"
        "<tr><td>18</td><td>200</td></tr>"
        "<tr><td>19</td><td>230</td></tr>"
        "</table>",
        row_band=0, col_band=1, chunk_id="long-right",
        anchor_bbox=(0, 0, 40, 100),
    )
    result = TableRowAssembler().assemble([left, right])
    assert "<td>18</td><td>100</td><td>200</td>" in result.markdown
    # 右块第 2 行追加 (不丢失)
    assert "<td>19</td><td>230</td>" in result.markdown
    assert result.assembled_tables == 1
