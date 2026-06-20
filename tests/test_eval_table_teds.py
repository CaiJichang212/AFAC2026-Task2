import time

from finix_restore.eval.table_teds import (
    LARGE_TABLE_NODE_THRESHOLD,
    _approx_teds,
    has_any_table,
    table_teds,
)
from finix_restore.eval.tables import extract_tables


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


def test_small_table_uses_exact_path_unchanged():
    md = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    assert table_teds(md, md) == 100.0

    pred = "<table><tr><td>A</td><td>X</td></tr></table>"
    gt = "<table><tr><td>A</td><td>B</td></tr></table>"
    score = table_teds(pred, gt)
    assert 0.0 < score < 100.0


def _build_big_table(third_cell: str = "c") -> str:
    rows = "".join(
        f"<tr><td>a</td><td>b</td><td>{third_cell}</td></tr>" for _ in range(300)
    )
    return f"<table>{rows}</table>"


def test_large_table_uses_approximation_and_is_fast():
    big = _build_big_table()
    # 1 table + 300 tr + 900 td = 1201 节点，超过阈值，应走近似分支。
    assert LARGE_TABLE_NODE_THRESHOLD < 1201

    start = time.perf_counter()
    score = table_teds(big, big)
    elapsed = time.perf_counter() - start
    assert score == 100.0
    assert elapsed < 2.0

    # 构造少量单元格差异的大表（仅最后一行第三列不同）。
    rows = "".join(
        "<tr><td>a</td><td>b</td><td>c</td></tr>" for _ in range(299)
    ) + "<tr><td>a</td><td>b</td><td>DIFF</td></tr>"
    pred2 = f"<table>{rows}</table>"
    diff_score = table_teds(pred2, big)
    assert 0.0 < diff_score < 100.0


def test_approx_teds_branch_returns_reasonable_value():
    big = _build_big_table()
    tree = extract_tables(big)[0]
    assert _approx_teds(tree, tree) == 100.0

    pred_tree = extract_tables(_build_big_table(third_cell="z"))[0]
    score = _approx_teds(pred_tree, tree)
    assert 0.0 < score < 100.0


def test_huge_table_approximation_is_fast():
    # 1 table + 4000 tr + 12000 td = 16001 节点，远超阈值，必须走 rapidfuzz 近似分支。
    big = (
        "<table>"
        + "".join(
            "<tr><td>a</td><td>b</td><td>c</td></tr>" for _ in range(4000)
        )
        + "</table>"
    )
    start = time.perf_counter()
    score = table_teds(big, big)
    elapsed = time.perf_counter() - start
    assert score == 100.0
    assert elapsed < 2.0
