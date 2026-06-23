from __future__ import annotations

import json
from pathlib import Path

from scripts.chunk_eval.summarize_metrics import load_metric_summary, render_metric_table
from scripts.chunk_eval.write_final_report import write_report


def test_load_metric_summary_extracts_top_worst(tmp_path: Path):
    metrics = {
        "file_count": 2,
        "mean_text_edit": 0.2,
        "mean_table_teds": 50.0,
        "mean_read_order_edit": 0.3,
        "mean_overall": 66.67,
        "table_sample_count": 1,
        "files": [
            {"file_name": "good.png", "overall": 90.0, "text_edit": 0.1, "table_teds": None, "read_order_edit": 0.1},
            {"file_name": "bad.png", "overall": 20.0, "text_edit": 0.8, "table_teds": 10.0, "read_order_edit": 0.7},
        ],
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics), encoding="utf-8")

    summary = load_metric_summary("long", path, top_n=1)

    assert summary["subset"] == "long"
    assert summary["file_count"] == 2
    assert summary["worst_files"][0]["file_name"] == "bad.png"


def test_render_metric_table_outputs_markdown():
    rows = [
        {
            "subset": "long",
            "file_count": 2,
            "mean_text_edit": 0.2,
            "mean_table_teds": 50.0,
            "mean_read_order_edit": 0.3,
            "mean_overall": 66.67,
            "table_sample_count": 1,
            "worst_files": [],
        }
    ]

    markdown = render_metric_table(rows)

    assert "| subset | files | Text Edit | Table TEDS | Read Order Edit | Overall |" in markdown
    assert "| long | 2 | 0.2000 | 50.00 | 0.3000 | 66.67 |" in markdown


def test_write_report_includes_sections(tmp_path: Path):
    out = tmp_path / "final_report.md"
    write_report(
        out,
        title="Report",
        dry_run_summary="dry run text",
        s2_summary="s2 text",
        s3_summary="s3 text",
        findings=["API failures dominate", "Table TEDS remains low"],
        next_steps=["Lower table target to 4M"],
    )

    text = out.read_text(encoding="utf-8")
    assert "# Report" in text
    assert "## 失分原因定位" in text
    assert "- API failures dominate" in text
