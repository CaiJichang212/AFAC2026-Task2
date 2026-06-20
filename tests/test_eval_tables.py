from finix_restore.eval.tables import TableNode, extract_tables


def test_extract_html_table_with_spans():
    markdown = (
        "intro\n"
        '<table><tr><td rowspan="2">A</td><td colspan="2">B</td></tr>'
        "<tr><td>C</td><td>D</td></tr></table>\n"
        "outro"
    )
    tables = extract_tables(markdown)
    assert len(tables) == 1
    root = tables[0]
    assert root.tag == "table"
    assert len(root.children) == 2
    first_row = root.children[0]
    assert first_row.tag == "tr"
    first_cell = first_row.children[0]
    assert isinstance(first_cell, TableNode)
    assert first_cell.tag == "td"
    assert first_cell.text == "A"
    assert first_cell.rowspan == 2
    assert first_row.children[1].colspan == 2


def test_extract_markdown_pipe_table():
    markdown = "| h1 | h2 |\n|---|---|\n| a | b |\n"
    tables = extract_tables(markdown)
    assert len(tables) == 1
    root = tables[0]
    assert root.tag == "table"
    assert len(root.children) == 2
    assert root.children[0].children[0].text == "h1"
    assert root.children[1].children[1].text == "b"


def test_extract_no_table_returns_empty():
    assert extract_tables("# title\nplain paragraph") == []
