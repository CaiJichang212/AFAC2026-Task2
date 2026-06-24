from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.chunk_eval.validate_submission import main, validate_submission


def _write_csv(
    path: Path,
    rows: list[tuple[str, str]],
    header: tuple[str, str] = ("file_name", "ground_truth"),
) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def test_validate_submission_accepts_valid_csv(tmp_path: Path):
    csv_path = tmp_path / "submission.csv"
    _write_csv(csv_path, [("a.png", "A"), ("b.png", "")])

    report = validate_submission(csv_path, expected_count=2)

    assert report["passed"] is True
    assert report["rows"] == 2
    assert report["empty_outputs"] == 1
    assert report["duplicate_file_names"] == []


def test_validate_submission_rejects_bad_header(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    _write_csv(csv_path, [("a.png", "A")], header=("name", "text"))

    with pytest.raises(ValueError, match="columns"):
        validate_submission(csv_path, expected_count=1)


def test_validate_submission_reports_duplicate_and_count(tmp_path: Path):
    csv_path = tmp_path / "dup.csv"
    _write_csv(csv_path, [("a.png", "A"), ("a.png", "B")])

    report = validate_submission(csv_path, expected_count=3)

    assert report["passed"] is False
    assert report["rows"] == 2
    assert report["duplicate_file_names"] == ["a.png"]
    assert "row_count_mismatch" in report["risks"]


def test_validate_submission_cli_blocks_requested_qc_risks(tmp_path: Path):
    csv_path = tmp_path / "submission.csv"
    _write_csv(csv_path, [("a.png", "A")])
    expected_dir = tmp_path / "images"
    expected_dir.mkdir()
    (expected_dir / "a.png").write_bytes(b"image")
    qc_summary = tmp_path / "summary.json"
    qc_summary.write_text(
        json.dumps(
            {
                "risk_counts": {"html_broken": 1},
                "failed_files": ["a.png"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--csv",
            str(csv_path),
            "--expected-dir",
            str(expected_dir),
            "--qc-summary",
            str(qc_summary),
            "--fail-on-risk",
            "html_broken",
            "--out",
            str(out_path),
        ]
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report["passed"] is False
    assert report["blocked_risks"] == ["html_broken"]
    assert report["risk_counts"]["html_broken"] == 1
