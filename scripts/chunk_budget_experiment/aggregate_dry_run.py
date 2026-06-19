"""Aggregate dry-run chunk manifests + QC into a per-budget CSV.

Layout expected under --root:
    <budget>/<dataset_label>/{chunks,profiles,qc,merged}/...

Output CSV columns:
    budget, dataset, doc_type, files, chunks_total,
    chunks_p50, chunks_p95, max_chunk_pixels,
    over_safe_total, over_hard_total
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    # nearest-rank percentile, robust for small samples.
    rank = max(1, min(len(sorted_values), int(round(pct / 100.0 * len(sorted_values)))))
    return sorted_values[rank - 1]


def _scan_run(work_dir: Path) -> list[dict]:
    """Scan one (budget, dataset) work_dir, return per-file rows."""
    rows: list[dict] = []
    chunks_dir = work_dir / "chunks"
    qc_dir = work_dir / "qc"
    if not chunks_dir.exists():
        return rows
    for stem_dir in sorted(p for p in chunks_dir.iterdir() if p.is_dir()):
        manifest_path = stem_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        qc_path = qc_dir / f"{stem_dir.name}.json"
        qc = (
            json.loads(qc_path.read_text(encoding="utf-8")) if qc_path.exists() else {}
        )
        metrics = qc.get("metrics", {})
        chunks = manifest.get("chunks", [])
        max_px = max((c.get("chunk_pixels", 0) for c in chunks), default=0)
        over_safe = sum(
            1 for c in chunks if "over_safe_pixels" in (c.get("risk_flags") or [])
        )
        over_hard = int(metrics.get("over_hard_chunks", 0))
        rows.append(
            {
                "doc_type": manifest.get("doc_type", "unknown"),
                "chunks": len(chunks),
                "max_chunk_pixels": max_px,
                "over_safe": over_safe,
                "over_hard": over_hard,
            }
        )
    return rows


def aggregate(root: Path) -> list[dict]:
    summary: list[dict] = []
    for budget_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for dataset_dir in sorted(p for p in budget_dir.iterdir() if p.is_dir()):
            file_rows = _scan_run(dataset_dir)
            if not file_rows:
                continue
            buckets: dict[str, list[dict]] = defaultdict(list)
            for row in file_rows:
                buckets[row["doc_type"]].append(row)
            for doc_type, rows in buckets.items():
                chunks_list = [r["chunks"] for r in rows]
                summary.append(
                    {
                        "budget": budget_dir.name,
                        "dataset": dataset_dir.name,
                        "doc_type": doc_type,
                        "files": len(rows),
                        "chunks_total": sum(chunks_list),
                        "chunks_p50": _percentile(chunks_list, 50),
                        "chunks_p95": _percentile(chunks_list, 95),
                        "max_chunk_pixels": max(
                            (r["max_chunk_pixels"] for r in rows), default=0
                        ),
                        "over_safe_total": sum(r["over_safe"] for r in rows),
                        "over_hard_total": sum(r["over_hard"] for r in rows),
                    }
                )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows = aggregate(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "budget",
        "dataset",
        "doc_type",
        "files",
        "chunks_total",
        "chunks_p50",
        "chunks_p95",
        "max_chunk_pixels",
        "over_safe_total",
        "over_hard_total",
    ]
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"wrote {len(rows)} rows -> {args.out}")
    # Light human-readable echo.
    if rows:
        ordering = sorted(rows, key=lambda r: (r["budget"], r["dataset"], r["doc_type"]))
        for row in ordering:
            print(
                f"  {row['budget']:>3} {row['dataset']:<12} {row['doc_type']:<12} "
                f"files={row['files']:<3} chunks_total={row['chunks_total']:<5} "
                f"max_px={row['max_chunk_pixels']:<8} "
                f"over_safe={row['over_safe_total']} over_hard={row['over_hard_total']}"
            )
    # silence unused import
    _ = statistics
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
