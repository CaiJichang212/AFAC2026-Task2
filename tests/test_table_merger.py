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


def test_repair_does_not_wrap_fragment_with_html_or_body():
    repaired = TableMerger().repair(
        "<html><body><table><tr><td>A</td></tr></table></body></html>"
    ).markdown

    assert "<html" not in repaired.lower()
    assert "<body" not in repaired.lower()


def test_repair_closes_multiple_broken_tables_for_quality_gate(tmp_path):
    from finix_restore.paths import RunPaths
    from finix_restore.quality_gate import QualityGate

    html = "<table><tr><td>A</td></tr>\n<table><tr><td>B</td></tr>"

    repaired = TableMerger().repair(html)
    report = QualityGate(RunPaths.from_work_dir(tmp_path / "work")).check_file(
        file_name="table.png",
        markdown=repaired.markdown,
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert repaired.repaired_tags > 0
    assert report.passed
    assert "html_broken" not in report.risks


def test_repair_preserves_span_empty_td_and_text_order():
    html = (
        "前文"
        "<table><tr><td rowspan=\"2\">A</td><td colspan=\"2\">B</td></tr>"
        "<tr><td></td><td>C</td></tr>"
        "后文"
    )

    repaired = TableMerger().repair(html).markdown

    assert "<html" not in repaired.lower()
    assert "<body" not in repaired.lower()
    assert 'rowspan="2"' in repaired
    assert 'colspan="2"' in repaired
    assert "<td></td>" in repaired
    assert repaired.startswith("前文<table>")
    assert repaired.endswith("</table>后文")
