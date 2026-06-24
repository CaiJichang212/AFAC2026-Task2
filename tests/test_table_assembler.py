from pathlib import Path

from finix_restore.models import Chunk, ChunkText
from finix_restore.table_assembler import TableRowAssembler


def _chunk_text(markdown: str, *, row_band: int, col_band: int, chunk_id: str) -> ChunkText:
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
