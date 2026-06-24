from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


_raise_csv_field_limit()


def _load_metrics(path: Path) -> dict[str, float | int]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "file_count": int(data.get("file_count", 0)),
        "mean_text_edit": float(data.get("mean_text_edit", 0.0)),
        "mean_table_teds": float(data.get("mean_table_teds", 0.0)),
        "mean_read_order_edit": float(data.get("mean_read_order_edit", 0.0)),
        "mean_overall": float(data.get("mean_overall", 0.0)),
    }


def _read_submission_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["file_name", "ground_truth"]:
            raise ValueError(f"unexpected CSV columns in {path}: {reader.fieldnames}")
        return list(reader)


def _count_tables(markdown: str) -> int:
    return markdown.lower().count("<table")


def _load_ground_truth(gt_dir: Path, file_name: str) -> str:
    stem = Path(file_name).stem
    path = Path(gt_dir) / f"{stem}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _quantile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summarize_length_ratios(rows: list[dict[str, str]], gt_dir: Path) -> dict[str, float]:
    ratios: list[float] = []
    for row in rows:
        pred = (row.get("ground_truth") or "").strip()
        gt = _load_ground_truth(gt_dir, row.get("file_name") or "").strip()
        ratios.append(len(pred) / max(1, len(gt)))
    return {
        "p10": _quantile(ratios, 0.10),
        "p50": _quantile(ratios, 0.50),
        "p90": _quantile(ratios, 0.90),
    }


def _summarize_table_count_deltas(rows: list[dict[str, str]], gt_dir: Path) -> dict[str, int]:
    more = 0
    same = 0
    less = 0
    for row in rows:
        pred_tables = _count_tables(row.get("ground_truth") or "")
        gt_tables = _count_tables(_load_ground_truth(gt_dir, row.get("file_name") or ""))
        if pred_tables > gt_tables:
            more += 1
        elif pred_tables < gt_tables:
            less += 1
        else:
            same += 1
    return {
        "pred_tables > gt_tables": more,
        "pred_tables = gt_tables": same,
        "pred_tables < gt_tables": less,
    }


def _manifest_shape(manifest: dict) -> str:
    chunks = manifest.get("chunks") or []
    row_values: list[int] = []
    col_values: list[int] = []
    for entry in chunks:
        variant_kind = str(entry.get("variant_kind") or "")
        if variant_kind == "full_page_reference":
            continue
        row_value = entry.get("row_band", entry.get("row"))
        col_value = entry.get("col_band", entry.get("col"))
        if isinstance(row_value, int) and row_value >= 0:
            row_values.append(row_value)
        if isinstance(col_value, int) and col_value >= 0:
            col_values.append(col_value)
    if not row_values or not col_values:
        return "unknown"
    return f"{max(row_values) + 1}x{max(col_values) + 1}"


def _chunk_shape_distribution(run_dir: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for manifest_path in sorted((Path(run_dir) / "chunks").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        counts[_manifest_shape(manifest)] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _risk_counts(run_dir: Path) -> dict[str, int]:
    path = Path(run_dir) / "qc" / "summary.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_counts = data.get("risk_counts") or {}
    return {str(key): int(value) for key, value in raw_counts.items()}


def _render_kv_table(rows: list[tuple[str, str]]) -> str:
    lines = ["| metric | value |", "| --- | ---: |"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def build_table_failure_summary(
    metrics_path: Path,
    pred_csv: Path,
    gt_dir: Path,
    run_dir: Path,
) -> str:
    metrics = _load_metrics(metrics_path)
    pred_rows = _read_submission_rows(pred_csv)
    length_ratios = _summarize_length_ratios(pred_rows, gt_dir)
    table_deltas = _summarize_table_count_deltas(pred_rows, gt_dir)
    shape_distribution = _chunk_shape_distribution(run_dir)
    risk_counts = _risk_counts(run_dir)

    sections = [
        "## 指标汇总",
        _render_kv_table(
            [
                ("file_count", str(metrics["file_count"])),
                ("mean_text_edit", f"{metrics['mean_text_edit']:.4f}"),
                ("mean_table_teds", f"{metrics['mean_table_teds']:.4f}"),
                ("mean_read_order_edit", f"{metrics['mean_read_order_edit']:.4f}"),
                ("mean_overall", f"{metrics['mean_overall']:.4f}"),
            ]
        ),
        "## 长度比分位数",
        _render_kv_table([(label, f"{value:.4f}") for label, value in length_ratios.items()]),
        "## 表格数偏差",
        _render_kv_table([(label, str(value)) for label, value in table_deltas.items()]),
        "## Chunk Shape 分布",
        _render_kv_table([(label, str(value)) for label, value in shape_distribution.items()]),
        "## QC 风险计数",
        _render_kv_table([(label, str(value)) for label, value in sorted(risk_counts.items())]),
    ]
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize AFAC table failure signals into Markdown")
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--gt-dir", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    markdown = build_table_failure_summary(args.metrics, args.pred, args.gt_dir, args.run_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
