from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest


def _load_module():
    try:
        return import_module("scripts.chunk_eval.analyze_long_metrics")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing scripts.chunk_eval.analyze_long_metrics: {exc}")


def test_analyze_long_metrics_reports_table_count_mismatch(tmp_path: Path):
    module = _load_module()
    metrics_path = tmp_path / "metrics.json"
    submission_path = tmp_path / "submission.csv"
    gt_dir = tmp_path / "gt"
    manifest_dir = tmp_path / "chunks"
    gt_dir.mkdir()
    manifest_dir.mkdir()

    metrics = {
        "file_count": 2,
        "mean_text_edit": 0.2,
        "mean_table_teds": 6.0,
        "mean_read_order_edit": 0.3,
        "mean_overall": 70.0,
        "files": [
            {
                "file_name": "no-table.png",
                "text_edit": 0.1,
                "table_teds": None,
                "read_order_edit": 0.2,
                "has_table": False,
                "overall": 80.0,
            },
            {
                "file_name": "with-table.png",
                "text_edit": 0.3,
                "table_teds": 12.0,
                "read_order_edit": 0.4,
                "has_table": True,
                "overall": 60.0,
            },
        ],
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")

    pd.DataFrame(
        [
            {"file_name": "no-table.png", "ground_truth": "# 正文"},
            {
                "file_name": "with-table.png",
                "ground_truth": (
                    "<table><tr><td>项目</td></tr><tr><td>A</td></tr></table>\n"
                    "<table><tr><td>项目</td></tr><tr><td>B</td></tr></table>"
                ),
            },
        ]
    ).to_csv(submission_path, index=False)

    (gt_dir / "no-table.md").write_text("# 正文\n", encoding="utf-8")
    (gt_dir / "with-table.md").write_text(
        "<table><tr><td>项目</td></tr><tr><td>A</td></tr></table>\n",
        encoding="utf-8",
    )

    for stem, cuts in {
        "no-table": ["blank_band", "fixed_cut"],
        "with-table": ["blank_band", "blank_band"],
    }.items():
        sample_dir = manifest_dir / stem
        sample_dir.mkdir()
        payload = {
            "file_name": f"{stem}.png",
            "chunks": [
                {"cut_source": cut, "is_last_row": index == len(cuts) - 1}
                for index, cut in enumerate(cuts)
            ],
        }
        (sample_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    summary = module.analyze_long_metrics(metrics_path, submission_path, gt_dir, manifest_dir)

    assert summary["total"]["file_count"] == 2
    assert summary["by_has_table"]["true"]["file_count"] == 1
    assert summary["table_count_mismatch"]["file_count"] == 1
    assert summary["table_count_mismatch"]["mean_table_teds"] == 12.0
