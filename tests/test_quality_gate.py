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


def test_retry_planner_maps_risks_to_actions():
    from finix_restore.models import QualityReport
    from finix_restore.retry_planner import RetryPlanner

    report = QualityReport(
        passed=False,
        risks=["empty_output", "too_short", "html_broken", "api_timeout"],
        metrics={},
    )

    plan = RetryPlanner(max_reruns_per_file=2).plan(report, rerun_count=0)

    assert plan["rerun"] is True
    assert plan["window_scale"] == 0.7
    assert plan["overlap_scale"] == 1.5
    assert plan["table_grid_scale"] == 0.7
    assert plan["concurrency"] == 1

    exhausted = RetryPlanner(max_reruns_per_file=1).plan(report, rerun_count=1)
    assert exhausted["rerun"] is False
