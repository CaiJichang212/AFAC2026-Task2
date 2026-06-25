from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finix_restore.eval.tables import extract_tables


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _metric_float(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return 0.0 if value is None else float(value)


def _load_submission(path: Path) -> dict[str, str]:
    df = pd.read_csv(path).fillna("")
    return {str(row["file_name"]): str(row["ground_truth"]) for _, row in df.iterrows()}


def _load_gt_text(gt_dir: Path, file_name: str) -> str:
    path = gt_dir / f"{Path(file_name).stem}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _cutline_metrics(manifest_dir: Path, file_name: str) -> dict[str, float | int]:
    manifest_path = manifest_dir / Path(file_name).stem / "manifest.json"
    if not manifest_path.exists():
        return {"blank_cut_count": 0, "fixed_cut_count": 0, "blank_cut_ratio": 0.0}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    blank_cut_count = 0
    fixed_cut_count = 0
    chunks = payload.get("chunks", [])
    for index, chunk in enumerate(chunks):
        is_last = bool(chunk.get("is_last_row")) or index == len(chunks) - 1
        if is_last:
            continue
        if chunk.get("cut_source") == "blank_band":
            blank_cut_count += 1
        else:
            fixed_cut_count += 1
    total = blank_cut_count + fixed_cut_count
    return {
        "blank_cut_count": blank_cut_count,
        "fixed_cut_count": fixed_cut_count,
        "blank_cut_ratio": blank_cut_count / max(1, total),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "file_count": len(rows),
        "mean_text_edit": _mean([_metric_float(row, "text_edit") for row in rows]),
        "mean_table_teds": _mean([_metric_float(row, "table_teds") for row in rows if row.get("table_teds") is not None]),
        "mean_read_order_edit": _mean([_metric_float(row, "read_order_edit") for row in rows]),
        "mean_overall": _mean([_metric_float(row, "overall") for row in rows]),
        "mean_blank_cut_ratio": _mean([_metric_float(row, "blank_cut_ratio") for row in rows]),
        "mean_blank_cut_count": _mean([_metric_float(row, "blank_cut_count") for row in rows]),
        "mean_fixed_cut_count": _mean([_metric_float(row, "fixed_cut_count") for row in rows]),
    }


def _target_gap(summary: dict[str, Any]) -> dict[str, float]:
    return {
        "overall_to_80": max(0.0, 80.0 - float(summary.get("mean_overall", 0.0))),
        "text_edit_to_0_07": max(0.0, float(summary.get("mean_text_edit", 0.0)) - 0.07),
        "read_order_edit_to_0_50": max(0.0, float(summary.get("mean_read_order_edit", 0.0)) - 0.50),
        "table_teds_to_90": max(0.0, 90.0 - float(summary.get("mean_table_teds", 0.0))),
        "blank_cut_ratio_to_0_85": max(0.0, 0.85 - float(summary.get("mean_blank_cut_ratio", 0.0))),
    }


def analyze_long_metrics(
    metrics_path: Path,
    submission_path: Path,
    gt_dir: Path,
    manifest_dir: Path,
    worst_n: int = 20,
) -> dict[str, Any]:
    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    submission = _load_submission(Path(submission_path))

    rows: list[dict[str, Any]] = []
    for row in metrics.get("files", []):
        file_name = str(row["file_name"])
        pred_text = submission.get(file_name, "")
        gt_text = _load_gt_text(Path(gt_dir), file_name)
        gt_table_count = len(extract_tables(gt_text))
        pred_table_count = len(extract_tables(pred_text))
        cutline = _cutline_metrics(Path(manifest_dir), file_name)
        rows.append(
            {
                **row,
                "gt_table_count": gt_table_count,
                "pred_table_count": pred_table_count,
                "table_count_match": gt_table_count == pred_table_count,
                "blank_cut_count": cutline["blank_cut_count"],
                "fixed_cut_count": cutline["fixed_cut_count"],
                "blank_cut_ratio": cutline["blank_cut_ratio"],
            }
        )

    with_table = [row for row in rows if row["gt_table_count"] > 0]
    without_table = [row for row in rows if row["gt_table_count"] == 0]
    count_scoped = [row for row in rows if row["gt_table_count"] > 0 or row["pred_table_count"] > 0]
    count_match = [row for row in count_scoped if row["table_count_match"]]
    count_mismatch = [row for row in count_scoped if not row["table_count_match"]]
    worst_files = sorted(rows, key=lambda row: _metric_float(row, "overall"))[:worst_n]

    total = _summarize(rows)
    summary = {
        "total": total,
        "by_has_table": {
            "true": _summarize(with_table),
            "false": _summarize(without_table),
        },
        "table_count_match": _summarize(count_match),
        "table_count_mismatch": _summarize(count_mismatch),
        "worst_files": worst_files,
        "target_gap": _target_gap(total),
    }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    def row(label: str, payload: dict[str, Any]) -> str:
        return (
            f"| {label} | {payload['file_count']} | {payload['mean_text_edit']:.4f} | "
            f"{payload['mean_table_teds']:.2f} | {payload['mean_read_order_edit']:.4f} | "
            f"{payload['mean_overall']:.2f} | {payload['mean_blank_cut_ratio']:.4f} |"
        )

    lines = [
        "## Long 指标分桶",
        "| bucket | files | Text Edit | Table TEDS | Read Order Edit | Overall | Blank Cut Ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        row("total", summary["total"]),
        row("has_table=true", summary["by_has_table"]["true"]),
        row("has_table=false", summary["by_has_table"]["false"]),
        row("table_count_match", summary["table_count_match"]),
        row("table_count_mismatch", summary["table_count_mismatch"]),
        "",
        "## 最差 20 样本",
        "| file_name | Overall | Text Edit | Table TEDS | Read Order Edit | GT Tables | Pred Tables | Blank Cut Ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summary["worst_files"]:
        table_teds = "" if item.get("table_teds") is None else f"{float(item['table_teds']):.2f}"
        lines.append(
            f"| {item['file_name']} | {float(item['overall']):.2f} | {float(item['text_edit']):.4f} | "
            f"{table_teds} | {float(item['read_order_edit']):.4f} | {item['gt_table_count']} | "
            f"{item['pred_table_count']} | {float(item['blank_cut_ratio']):.4f} |"
        )
    lines.extend(
        [
            "",
            "## 80+ 目标缺口",
            json.dumps(summary["target_gap"], ensure_ascii=False, indent=2),
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze long metrics buckets and cutline stats")
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--gt-dir", required=True, type=Path)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    parser.add_argument("--worst-n", type=int, default=20)
    args = parser.parse_args(argv)

    summary = analyze_long_metrics(
        args.metrics,
        args.submission,
        args.gt_dir,
        args.manifest_dir,
        worst_n=args.worst_n,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(render_markdown(summary), encoding="utf-8")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
