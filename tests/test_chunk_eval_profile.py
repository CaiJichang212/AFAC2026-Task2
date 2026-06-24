from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

from PIL import Image

from scripts.chunk_eval.profile_train import build_profiles, write_profile_outputs


def _make_image(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)


def test_build_profiles_writes_expected_columns(tmp_path: Path):
    long_dir = tmp_path / "long"
    table_dir = tmp_path / "table"
    _make_image(long_dir / "long_a.png", (100, 1200))
    _make_image(table_dir / "table_a.png", (3600, 4800))

    rows = build_profiles({"long": long_dir, "table": table_dir})

    assert [row["subset"] for row in rows] == ["long", "table"]
    assert rows[0]["file_name"] == "long_a.png"
    assert rows[0]["doc_type"] == "long_strip"
    assert rows[1]["doc_type"] == "table_page"
    assert "pixel_bucket" in rows[0]


def test_write_profile_outputs_creates_csvs(tmp_path: Path):
    rows = [
        {
            "subset": "long",
            "file_name": "a.png",
            "width": 100,
            "height": 1200,
            "pixels": 120000,
            "aspect": "12.0000",
            "doc_type": "long_strip",
            "risk_level": "low",
            "pixel_bucket": "p000_p020",
        },
        {
            "subset": "table",
            "file_name": "b.png",
            "width": 3600,
            "height": 4800,
            "pixels": 17280000,
            "aspect": "1.3333",
            "doc_type": "table_page",
            "risk_level": "medium",
            "pixel_bucket": "p080_p100",
        },
    ]

    write_profile_outputs(rows, tmp_path)

    profile_csv = tmp_path / "train_profile.csv"
    summary_csv = tmp_path / "bucket_summary.csv"
    assert profile_csv.exists()
    assert summary_csv.exists()
    profile_rows = list(csv.DictReader(profile_csv.open(encoding="utf-8")))
    summary_rows = list(csv.DictReader(summary_csv.open(encoding="utf-8")))
    assert len(profile_rows) == 2
    assert summary_rows[0]["subset"] == "long"


def test_profile_train_script_help_runs_from_repo_root():
    script = Path("scripts/chunk_eval/profile_train.py")

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Profile AFAC Task2 train images" in result.stdout
