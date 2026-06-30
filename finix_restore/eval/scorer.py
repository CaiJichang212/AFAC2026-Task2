from __future__ import annotations

import json
from pathlib import Path

from finix_restore.eval.io import load_pairs
from finix_restore.eval.reading_order import read_order_edit
from finix_restore.eval.table_teds import table_teds
from finix_restore.eval.text_metric import text_edit


def score_pair(file_name: str, pred: str, gt: str) -> dict:
    te = text_edit(pred, gt)
    teds = table_teds(pred, gt)
    roe = read_order_edit(pred, gt)
    has_table = teds is not None
    table_component = teds if has_table else 100.0
    # te/roe 按赛题口径以 len(gt) 归一化，pred 远长于 gt 时可能 >1。
    # 线上 overall 直接代入会爆负分，丢失区分度；本地诊断时裁剪到 [0,1]。
    te_clamped = min(1.0, te)
    roe_clamped = min(1.0, roe)
    raw_overall = ((1 - te) * 100 + table_component + (1 - roe) * 100) / 3
    overall = ((1 - te_clamped) * 100 + table_component + (1 - roe_clamped) * 100) / 3
    return {
        "file_name": file_name,
        "text_edit": te,
        "table_teds": teds,
        "read_order_edit": roe,
        "has_table": has_table,
        "overall": overall,
        "raw_overall": raw_overall,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(pred_path, gt_path, mapping_csv=None, output=None) -> dict:
    pairs, missing_gt, missing_pred = load_pairs(pred_path, gt_path, mapping_csv)

    files = [score_pair(name, pred, gt) for name, pred, gt in pairs]
    table_scores = [f["table_teds"] for f in files if f["has_table"]]

    report = {
        "file_count": len(files),
        "missing_gt": missing_gt,
        "missing_pred": missing_pred,
        "mean_text_edit": _mean([f["text_edit"] for f in files]),
        "mean_read_order_edit": _mean([f["read_order_edit"] for f in files]),
        "mean_table_teds": _mean(table_scores),
        "table_sample_count": len(table_scores),
        "mean_overall": _mean([f["overall"] for f in files]),
        "files": files,
    }

    if output is not None:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return report
