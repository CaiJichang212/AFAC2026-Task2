from __future__ import annotations

import csv
import json
from pathlib import Path

from finix_restore.eval.scorer import evaluate, score_pair


def test_score_pair_no_table():
    text = "# A\n\nbody"
    r = score_pair("doc.png", text, text)
    assert r["text_edit"] == 0.0
    assert r["read_order_edit"] == 0.0
    assert r["table_teds"] is None
    assert r["has_table"] is False
    assert r["overall"] == 100.0


def test_score_pair_with_table():
    text = "<table><tr><td>A</td></tr></table>"
    r = score_pair("doc.png", text, text)
    assert r["has_table"] is True
    assert r["table_teds"] == 100.0
    assert r["overall"] == 100.0


def test_score_pair_overall_clamps_negative_loss():
    # pred far longer than gt -> text_edit/read_order_edit exceed 1.0 by design.
    # overall must stay within [0, 100]; raw_overall preserves the unclamped value.
    gt = "A"
    pred = "A" + "X" * 500
    r = score_pair("doc.png", pred, gt)
    assert r["text_edit"] > 1.0
    assert r["overall"] >= 0.0
    assert r["overall"] <= 100.0
    assert r["raw_overall"] < 0.0


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file_name", "ground_truth"])
        for name, content in rows:
            writer.writerow([name, content])


def test_evaluate_aggregate(tmp_path: Path):
    rows = [
        ("t.png", "<table><tr><td>A</td></tr></table>"),
        ("p.png", "# Title"),
    ]
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    _write_csv(pred, rows)
    _write_csv(gt, rows)
    out = tmp_path / "report" / "report.json"

    report = evaluate(pred, gt, output=out)
    assert report["file_count"] == 2
    assert report["mean_overall"] == 100.0
    assert report["mean_table_teds"] == 100.0
    assert report["table_sample_count"] == 1

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["mean_overall"] == 100.0
