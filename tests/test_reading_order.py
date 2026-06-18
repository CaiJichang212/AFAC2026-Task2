from pathlib import Path

from finix_restore.models import Chunk, ChunkText
from finix_restore.reading_order import ReadingOrderResolver


def _chunk(file_name: str, bbox, row=0, col=0) -> Chunk:
    return Chunk(
        chunk_id=f"{file_name}-{row}-{col}-{bbox}",
        file_name=file_name,
        image_path=Path(f"/tmp/{file_name}.jpg"),
        bbox=bbox,
        row=row,
        col=col,
        overlap={},
        image_sha1="sha",
    )


def _chunk_text(file_name: str, markdown: str, bbox, row=0, col=0) -> ChunkText:
    return ChunkText(
        chunk=_chunk(file_name, bbox, row=row, col=col),
        markdown=markdown,
        block_type="body",
        source="manual_fixture",
    )


def test_long_strip_order_uses_y_then_x_coordinates():
    chunks = [
        _chunk_text("doc.png", "third", (100, 300, 200, 400)),
        _chunk_text("doc.png", "first", (0, 0, 100, 100)),
        _chunk_text("doc.png", "second", (10, 300, 80, 400)),
    ]

    ordered = ReadingOrderResolver().resolve(chunks, doc_type="long_strip")

    assert [item.markdown for item in ordered] == ["first", "second", "third"]


def test_table_order_uses_row_then_col_and_skips_reference_full_page_chunk():
    chunks = [
        _chunk_text("table.png", "r1c1", (100, 100, 200, 200), row=1, col=1),
        _chunk_text("table.png", "full page reference", (0, 0, 400, 400), row=-1, col=-1),
        _chunk_text("table.png", "r0c1", (100, 0, 200, 100), row=0, col=1),
        _chunk_text("table.png", "r0c0", (0, 0, 100, 100), row=0, col=0),
    ]

    ordered = ReadingOrderResolver().resolve(chunks, doc_type="table_page")

    assert [item.markdown for item in ordered] == ["r0c0", "r0c1", "r1c1"]


def test_toc_block_is_marked_and_not_treated_as_body():
    toc = _chunk_text("doc.png", "# 条款目录\n1 总则\n2 保险责任", (0, 0, 100, 100))
    body = _chunk_text("doc.png", "# 1 总则\n正文", (0, 100, 100, 200))

    ordered = ReadingOrderResolver().resolve([body, toc], doc_type="long_strip")

    assert ordered[0].block_type == "toc"
    assert ordered[1].block_type == "body"
