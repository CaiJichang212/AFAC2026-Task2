from pathlib import Path

from finix_restore.models import Chunk, ChunkText
from finix_restore.table_parser import TableChunkParser


def _chunk_text(markdown: str) -> ChunkText:
    return ChunkText(
        chunk=Chunk(
            chunk_id="c1",
            file_name="table.png",
            image_path=Path("/tmp/table.jpg"),
            bbox=(0, 0, 100, 100),
            row=0,
            col=0,
            overlap={"left": 0, "right": 0, "top": 0, "bottom": 0},
            image_sha1="sha1",
        ),
        markdown=markdown,
        block_type="table",
        source="manual_fixture",
    )


def test_table_chunk_parser_parses_td_rows():
    parsed = TableChunkParser().parse(
        _chunk_text("<table><tr><td>项目</td><td>金额</td></tr><tr><td>A</td><td>1</td></tr></table>")
    )

    assert tuple(tuple(cell.text for cell in row) for row in parsed.tables[0].rows) == (("项目", "金额"), ("A", "1"))
    assert parsed.tables[0].header_key == ("项目", "金额")
    assert parsed.tables[0].broken is False


def test_table_chunk_parser_parses_th_header_rows():
    parsed = TableChunkParser().parse(
        _chunk_text("<table><tr><th>项目</th><th>金额</th></tr><tr><td>A</td><td>1</td></tr></table>")
    )

    assert tuple(tuple(cell.text for cell in row) for row in parsed.tables[0].rows) == (("项目", "金额"), ("A", "1"))
    assert parsed.tables[0].header_key == ("项目", "金额")
    assert all(cell.is_header for cell in parsed.tables[0].rows[0])
    assert parsed.tables[0].rows[1][0].is_header is False


def test_table_chunk_parser_keeps_empty_td():
    parsed = TableChunkParser().parse(
        _chunk_text("<table><tr><td>A</td><td></td><td>C</td></tr></table>")
    )

    assert tuple(tuple(cell.text for cell in row) for row in parsed.tables[0].rows) == (("A", "", "C"),)
    assert parsed.tables[0].rows[0][1].text == ""


def test_table_chunk_parser_marks_broken_html_and_best_effort_rows():
    parsed = TableChunkParser().parse(
        _chunk_text("<table><tr><td>项目</td><td>金额</td></tr><tr><td>A</td><td>1")
    )

    assert tuple(tuple(cell.text for cell in row) for row in parsed.tables[0].rows) == (("项目", "金额"), ("A", "1"))
    assert parsed.tables[0].broken is True
    assert "html_broken" in parsed.warnings


def test_table_chunk_parser_preserves_non_table_text_in_leading_text():
    parsed = TableChunkParser().parse(_chunk_text("费率说明\n\n无表格正文"))

    assert parsed.tables == ()
    assert parsed.leading_text == "费率说明\n\n无表格正文"
    assert parsed.trailing_text == ""


def test_table_chunk_parser_preserves_span_metadata():
    parsed = TableChunkParser().parse(
        _chunk_text(
            "<table>"
            "<tr><th colspan=\"3\">费率表</th></tr>"
            "<tr><td rowspan=\"2\">18岁</td><td>男</td><td></td></tr>"
            "<tr><td>女</td><td>120</td></tr>"
            "</table>"
        )
    )

    title = parsed.tables[0].rows[0][0]
    age = parsed.tables[0].rows[1][0]
    empty_cell = parsed.tables[0].rows[1][2]

    assert title.is_header is True
    assert title.colspan == 3
    assert age.rowspan == 2
    assert empty_cell.text == ""
