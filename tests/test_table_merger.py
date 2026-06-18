from finix_restore.table_merger import TableMerger


def test_repairs_missing_table_tags_and_reports_count():
    html = "<table><tr><td>A</td><td>B"

    repaired = TableMerger().repair(html)

    assert repaired.repaired_tags > 0
    assert "<table" in repaired.markdown
    assert "</tr>" in repaired.markdown
    assert "</table>" in repaired.markdown
    assert "<td>B</td>" in repaired.markdown


def test_keep_empty_td():
    html = "<table><tr><td>A</td><td></td><td>C</td></tr></table>"

    repaired = TableMerger().repair(html).markdown

    assert "<td></td>" in repaired


def test_adjacent_duplicate_table_header_is_removed_once():
    html = (
        "<table><tr><th>项目</th><th>金额</th></tr><tr><td>A</td><td>1</td></tr></table>\n"
        "<table><tr><th>项目</th><th>金额</th></tr><tr><td>B</td><td>2</td></tr></table>"
    )

    repaired = TableMerger().repair(html).markdown

    assert repaired.count("<th>项目</th><th>金额</th>") == 1
    assert "<td>A</td><td>1</td>" in repaired
    assert "<td>B</td><td>2</td>" in repaired
