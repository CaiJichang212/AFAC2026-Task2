from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.chunk_eval.summarize_table_failures import build_table_failure_summary


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file_name", "ground_truth"])
        writer.writeheader()
        writer.writerows(rows)


def test_build_table_failure_summary_includes_key_sections(tmp_path: Path):
    metrics = {
        "file_count": 2,
        "mean_text_edit": 0.18,
        "mean_table_teds": 41.25,
        "mean_read_order_edit": 0.35,
        "mean_overall": 62.50,
        "files": [
            {"file_name": "alpha.png", "overall": 70.0},
            {"file_name": "beta.png", "overall": 55.0},
        ],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

    pred_csv = tmp_path / "pred.csv"
    _write_csv(
        pred_csv,
        [
            {
                "file_name": "alpha.png",
                "ground_truth": "<table><tr><td>A</td></tr></table>\n<table><tr><td>B</td></tr></table>",
            },
            {
                "file_name": "beta.png",
                "ground_truth": "<table><tr><td>Only</td></tr></table>",
            },
        ],
    )

    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "alpha.md").write_text("<table><tr><td>A</td></tr></table>", encoding="utf-8")
    (gt_dir / "beta.md").write_text("<table><tr><td>Only</td></tr></table>\nextra", encoding="utf-8")

    run_dir = tmp_path / "run"
    (run_dir / "chunks" / "alpha").mkdir(parents=True)
    (run_dir / "chunks" / "beta").mkdir(parents=True)
    (run_dir / "qc").mkdir(parents=True)
    (run_dir / "chunks" / "alpha" / "manifest.json").write_text(
        json.dumps(
            {
                "chunk_policy": "table_grid_v2",
                "chunks": [
                    {"row": 0, "col": 0},
                    {"row": 0, "col": 1},
                    {"row": 1, "col": 0},
                    {"row": 1, "col": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "chunks" / "beta" / "manifest.json").write_text(
        json.dumps(
            {
                "chunk_policy": "table_rowband_v2",
                "chunks": [
                    {"row_band": -1, "col_band": 0, "variant_kind": "full_page_reference"},
                    {"row_band": 0, "col_band": 0, "variant_kind": "table_crop"},
                    {"row_band": 1, "col_band": 0, "variant_kind": "table_crop"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "qc" / "summary.json").write_text(
        json.dumps(
            {
                "risk_counts": {
                    "html_broken": 1,
                    "high_duplication": 2,
                    "table_assembly_uncertain": 1,
                }
            }
        ),
        encoding="utf-8",
    )

    markdown = build_table_failure_summary(metrics_path, pred_csv, gt_dir, run_dir)

    assert "## 指标汇总" in markdown
    assert "| mean_overall | 62.5000 |" in markdown
    assert "## 长度比分位数" in markdown
    assert "| p50 |" in markdown
    assert "## 表格数偏差" in markdown
    assert "| pred_tables > gt_tables | 1 |" in markdown
    assert "## Chunk Shape 分布" in markdown
    assert "| 2x2 | 1 |" in markdown
    assert "| 2x1 | 1 |" in markdown
    assert "## QC 风险计数" in markdown
    assert "| high_duplication | 2 |" in markdown
