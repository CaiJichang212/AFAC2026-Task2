from finix_restore.eval.table_teds import has_any_table, table_teds


def test_identical_tables_score_100():
    md = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    assert table_teds(md, md) == 100.0


def test_different_cell_text_partial_score():
    pred = "<table><tr><td>A</td><td>X</td></tr></table>"
    gt = "<table><tr><td>A</td><td>B</td></tr></table>"
    score = table_teds(pred, gt)
    assert 0.0 < score < 100.0


def test_no_table_returns_none():
    assert table_teds("plain text", "plain text") is None


def test_has_any_table():
    assert has_any_table("<table><tr><td>A</td></tr></table>", "no table") is True
    assert has_any_table("none", "none") is False
