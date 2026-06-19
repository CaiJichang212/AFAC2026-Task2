"""Aggregate FinixDoc-VL API elapsed_ms from logs/run.jsonl, bucketed by doc_type.

Cross-references chunk_id -> doc_type via each run's chunks/*/manifest.json.
Only counts the *final* attempt per (run_id, chunk_id), so retries don't double-bill.

Output CSV columns:
    budget, doc_type, requests, elapsed_sum_s,
    elapsed_p50_ms, elapsed_p95_ms, elapsed_max_ms, fail_requests
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    rank = max(1, min(len(sorted_values), int(round(pct / 100.0 * len(sorted_values)))))
    return sorted_values[rank - 1]


def _build_chunk_doc_type_map(work_dir: Path) -> dict[str, str]:
    chunks_dir = work_dir / "chunks"
    if not chunks_dir.exists():
        return {}
    mapping: dict[str, str] = {}
    for stem_dir in chunks_dir.iterdir():
        manifest_path = stem_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc_type = manifest.get("doc_type", "unknown")
        for chunk in manifest.get("chunks", []):
            chunk_id = chunk.get("chunk_id")
            if chunk_id:
                mapping[chunk_id] = doc_type
    return mapping


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _final_calls(events: list[dict]) -> list[dict]:
    """Keep only the final attempt per (run_id, chunk_id)."""
    last_by_key: dict[tuple[str, str], dict] = {}
    for event in events:
        if event.get("event") != "api_call":
            continue
        key = (event.get("run_id", ""), event.get("chunk_id", ""))
        prev = last_by_key.get(key)
        if prev is None or int(event.get("retry_index", 0)) >= int(
            prev.get("retry_index", 0)
        ):
            last_by_key[key] = event
    return list(last_by_key.values())


def aggregate(root: Path) -> list[dict]:
    summary: list[dict] = []
    for budget_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        # Collect across all datasets under this budget; usually only a_table.
        per_doc_type: dict[str, list[int]] = defaultdict(list)
        per_doc_type_fail: dict[str, int] = defaultdict(int)
        for dataset_dir in sorted(p for p in budget_dir.iterdir() if p.is_dir()):
            log_path = dataset_dir / "logs" / "run.jsonl"
            if not log_path.exists():
                continue
            chunk_to_doc = _build_chunk_doc_type_map(dataset_dir)
            events = list(_read_jsonl(log_path))
            for event in _final_calls(events):
                doc_type = chunk_to_doc.get(event.get("chunk_id", ""), "unknown")
                elapsed = int(event.get("elapsed_ms", 0))
                status = event.get("status", "")
                per_doc_type[doc_type].append(elapsed)
                if status != "ok":
                    per_doc_type_fail[doc_type] += 1
        for doc_type, samples in per_doc_type.items():
            summary.append(
                {
                    "budget": budget_dir.name,
                    "doc_type": doc_type,
                    "requests": len(samples),
                    "elapsed_sum_s": round(sum(samples) / 1000.0, 2),
                    "elapsed_p50_ms": _percentile(samples, 50),
                    "elapsed_p95_ms": _percentile(samples, 95),
                    "elapsed_max_ms": max(samples) if samples else 0,
                    "fail_requests": per_doc_type_fail.get(doc_type, 0),
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
        "doc_type",
        "requests",
        "elapsed_sum_s",
        "elapsed_p50_ms",
        "elapsed_p95_ms",
        "elapsed_max_ms",
        "fail_requests",
    ]
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"wrote {len(rows)} rows -> {args.out}")
    for row in sorted(rows, key=lambda r: (r["budget"], r["doc_type"])):
        print(
            f"  {row['budget']:>3} {row['doc_type']:<12} "
            f"req={row['requests']:<3} sum={row['elapsed_sum_s']:>7.2f}s "
            f"p50={row['elapsed_p50_ms']:>6}ms p95={row['elapsed_p95_ms']:>6}ms "
            f"max={row['elapsed_max_ms']:>6}ms fail={row['fail_requests']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
