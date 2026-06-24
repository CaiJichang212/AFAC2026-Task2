import json

import pandas as pd

from finix_restore.paths import RunPaths


def test_submission_schema_rejects_bad_columns_row_count_and_duplicates(tmp_path):
    from finix_restore.quality_gate import QualityGate

    paths = RunPaths.from_work_dir(tmp_path / "work")
    gate = QualityGate(paths)
    bad_columns = tmp_path / "bad_columns.csv"
    pd.DataFrame([{"name": "a.png", "ground_truth": "x"}]).to_csv(bad_columns, index=False)

    report = gate.check_submission(bad_columns, expected_file_names=["a.png"])

    assert not report.passed
    assert "csv_columns" in report.risks

    duplicates = tmp_path / "duplicates.csv"
    pd.DataFrame(
        [
            {"file_name": "a.png", "ground_truth": "x"},
            {"file_name": "a.png", "ground_truth": "y"},
        ]
    ).to_csv(duplicates, index=False)

    report = gate.check_submission(duplicates, expected_file_names=["a.png", "b.png"])

    assert not report.passed
    assert "csv_duplicate_file_name" in report.risks
    assert "csv_file_name_mismatch" in report.risks


def test_duplicate_input_file_names_are_blocked_before_submission(tmp_path):
    from finix_restore.quality_gate import QualityGate

    input_a = tmp_path / "a"
    input_b = tmp_path / "b"
    input_a.mkdir()
    input_b.mkdir()
    (input_a / "same.png").write_bytes(b"a")
    (input_b / "same.png").write_bytes(b"b")

    report = QualityGate(RunPaths.from_work_dir(tmp_path / "work")).validate_input_files([input_a, input_b])

    assert not report.passed
    assert "duplicate_input_file_name" in report.risks


def test_file_quality_reports_empty_broken_html_duplication_and_api_failures(tmp_path):
    from finix_restore.quality_gate import QualityGate

    paths = RunPaths.from_work_dir(tmp_path / "work")
    gate = QualityGate(paths, max_duplication_ratio=0.10, max_api_failure_ratio=0.20)
    markdown = ("重复窗口" * 40) + "\n" + ("重复窗口" * 40) + "\n<table><tr><td>A"

    report = gate.check_file(
        file_name="doc.png",
        markdown=markdown,
        doc_type="table_page",
        chunk_count=10,
        failed_chunks=3,
    )

    assert not report.passed
    assert "html_broken" in report.risks
    assert "high_duplication" in report.risks
    assert "api_failure_ratio_high" in report.risks
    qc = json.loads((paths.qc_dir / "doc.json").read_text(encoding="utf-8"))
    assert qc["risks"] == report.risks

    empty = gate.check_file("empty.png", "", "long_strip", chunk_count=1, failed_chunks=0)
    assert "empty_output" in empty.risks


def test_quality_gate_flags_service_busy_html_page(tmp_path):
    from finix_restore.quality_gate import QualityGate

    paths = RunPaths.from_work_dir(tmp_path / "work")
    gate = QualityGate(paths)
    markdown = (
        "<!DOCTYPE html><html><head><title>busy</title></head><body>"
        "服务器繁忙 顾客太多 <div id='J_retry_link'></div><div class='showTextWait'></div>"
        "支付宝版权所有"
        "</body></html>"
    )

    report = gate.check_file(
        file_name="busy.png",
        markdown=markdown,
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert not report.passed
    assert "service_busy_html" in report.risks
    assert "full_html_page" in report.risks
    qc = json.loads((paths.qc_dir / "busy.json").read_text(encoding="utf-8"))
    assert "service_busy_html" in qc["risks"]
    assert "full_html_page" in qc["risks"]


def test_quality_gate_flags_service_busy_html_fragment(tmp_path):
    from finix_restore.quality_gate import QualityGate

    paths = RunPaths.from_work_dir(tmp_path / "work")
    gate = QualityGate(paths)
    markdown = (
        "<div class='wait-tit'>顾客太多，客官请稍候</div>\n"
        "<a id='J_retry_link'>重试</a>\n"
        "<script>showTextWait()</script>"
    )

    report = gate.check_file(
        file_name="busy-fragment.png",
        markdown=markdown,
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert not report.passed
    assert "service_busy_html" in report.risks
    assert "full_html_page" not in report.risks
    qc = json.loads((paths.qc_dir / "busy-fragment.json").read_text(encoding="utf-8"))
    assert "service_busy_html" in qc["risks"]


def test_quality_gate_allows_html_table_fragment(tmp_path):
    from finix_restore.quality_gate import QualityGate

    gate = QualityGate(RunPaths.from_work_dir(tmp_path / "work"))
    report = gate.check_file(
        file_name="table.png",
        markdown="<table><tr><td>保障责任</td></tr></table>",
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert "service_busy_html" not in report.risks
    assert "full_html_page" not in report.risks


def test_quality_gate_reports_table_html_status(tmp_path):
    from finix_restore.quality_gate import QualityGate

    gate = QualityGate(RunPaths.from_work_dir(tmp_path / "work"))

    healthy = gate.table_html_status("<table><tr><td>A</td></tr></table>")
    broken = gate.table_html_status("<table><tr><td>A")

    assert healthy["html_broken"] == 0
    assert broken["html_broken"] > 0


def test_retry_planner_maps_risks_to_actions():
    from finix_restore.models import QualityReport
    from finix_restore.retry_planner import RetryPlanner

    report = QualityReport(
        passed=False,
        risks=["empty_output", "too_short", "html_broken", "api_failure_ratio_high"],
        metrics={},
    )

    plan = RetryPlanner(max_reruns_per_file=2).plan(report, rerun_count=0)

    assert plan["rerun"] is True
    assert plan["force_api"] is True
    assert plan["window_scale"] == 1.0
    assert plan["overlap_scale"] == 1.5
    assert plan["table_grid_scale"] == 1.0
    assert plan["concurrency"] == 1

    exhausted = RetryPlanner(max_reruns_per_file=1).plan(report, rerun_count=1)
    assert exhausted["rerun"] is False


def test_retry_planner_for_html_risks_forces_api_and_serial_rerun():
    from finix_restore.models import QualityReport
    from finix_restore.retry_planner import RetryPlanner

    planner = RetryPlanner(max_reruns_per_file=2)

    for risk in ("service_busy_html", "full_html_page"):
        plan = planner.plan(QualityReport(passed=False, risks=[risk], metrics={}), rerun_count=0)
        assert plan["rerun"] is True
        assert plan["force_api"] is True
        assert plan["concurrency"] == 1
        assert plan["reasons"] == [risk]


def test_retry_planner_reruns_html_broken_table_outputs_serially():
    from finix_restore.models import QualityReport
    from finix_restore.retry_planner import RetryPlanner

    plan = RetryPlanner(max_reruns_per_file=2).plan(
        QualityReport(passed=False, risks=["html_broken"], metrics={}),
        rerun_count=0,
    )

    assert plan["rerun"] is True
    assert plan["concurrency"] == 1
    assert "html_broken" in plan["reasons"]


def test_quality_gate_detects_full_html_error_page_but_allows_table_fragment(tmp_path):
    from finix_restore.quality_gate import QualityGate

    gate = QualityGate(RunPaths.from_work_dir(tmp_path / "work"))

    broken = gate.check_file(
        file_name="broken.png",
        markdown=(
            "<!DOCTYPE html><html><head><title>busy</title></head>"
            "<body>服务器繁忙<div id='J_retry_link'></div></body></html>"
        ),
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert not broken.passed
    assert "full_html_page" in broken.risks

    allowed = gate.check_file(
        file_name="table.png",
        markdown="<table><tr><td>保障责任</td></tr></table>",
        doc_type="normal_page",
        chunk_count=1,
        failed_chunks=0,
    )

    assert "full_html_page" not in allowed.risks
    assert "html_broken" not in allowed.risks


def test_quality_gate_writes_run_summary_json(tmp_path):
    from finix_restore.models import ProcessedFile, QualityReport
    from finix_restore.quality_gate import QualityGate

    paths = RunPaths.from_work_dir(tmp_path / "work")
    gate = QualityGate(paths)
    processed = [
        ProcessedFile(
            file_name="ok.png",
            markdown="# ok",
            quality=QualityReport(passed=True, risks=[], metrics={"chars": 3}),
            rerun_count=0,
        ),
        ProcessedFile(
            file_name="bad.png",
            markdown="",
            quality=QualityReport(passed=False, risks=["empty_output"], metrics={"chars": 0}),
            rerun_count=2,
        ),
    ]

    summary = gate.write_run_summary(processed, output_csv=tmp_path / "submission.csv", dry_run=False)

    assert summary["passed"] is False
    assert summary["failed_files"] == ["bad.png"]
    assert summary["file_count"] == 2
    assert summary["output_csv"] == str(tmp_path / "submission.csv")
    assert summary["risk_counts"]["empty_output"] == 1
    assert summary["files"][1]["file_name"] == "bad.png"
    assert summary["files"][1]["rerun_count"] == 2

    persisted = json.loads((paths.qc_dir / "summary.json").read_text(encoding="utf-8"))
    assert persisted == summary
