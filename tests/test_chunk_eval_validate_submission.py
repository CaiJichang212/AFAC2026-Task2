from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.chunk_eval.validate_submission import validate_submission


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
