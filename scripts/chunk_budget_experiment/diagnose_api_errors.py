"""Diagnose FinixDoc-VL API failures from outputs/chunk_budget logs.

Cross-reference run.jsonl events with chunks/*/manifest.json to enrich each
event with (image_width, image_height, image_pixels, chunk_pixels). Then
report per-status / per-image-bucket statistics.

Usage:
  python scripts/chunk_budget_experiment/diagnose_api_errors.py \
    --root outputs/chunk_budget/api_smoke
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def _load_chunk_index(work_dir: Path):
    """chunk_id -> dict(file_name, image_w, image_h, image_pixels, chunk_pixels)."""
    index: dict[str, dict] = {}
    chunks_dir = work_dir / "chunks"
    if not chunks_dir.exists():
        return index
    for stem_dir in chunks_dir.iterdir():
        manifest_path = stem_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        w = int(manifest.get("width", 0))
        h = int(manifest.get("height", 0))
        for ch in manifest.get("chunks", []):
            cid = ch.get("chunk_id")
            if not cid:
                continue
            index[cid] = {
                "file_name": manifest.get("file_name", ""),
                "image_w": w,
                "image_h": h,
                "image_pixels": w * h,
                "chunk_pixels": int(ch.get("chunk_pixels", 0)),
            }
    return index


def _read_events(work_dir: Path):
    log = work_dir / "logs" / "run.jsonl"
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "api_call":
            continue
        out.append(event)
    return out


def _bucket_pixels(p: int) -> str:
    if p == 0:
        return "0"
    if p < 4_000_000:
        return "<4M"
    if p < 6_000_000:
        return "4-6M"
    if p < 8_000_000:
        return "6-8M"
    return ">=8M"


def _percentile(values, pct):
    if not values:
        return 0
    s = sorted(values)
    rank = max(1, min(len(s), int(round(pct / 100 * len(s)))))
    return s[rank - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    all_events: list[dict] = []
    for budget_dir in sorted(p for p in args.root.iterdir() if p.is_dir()):
        for ds_dir in sorted(p for p in budget_dir.iterdir() if p.is_dir()):
            chunk_index = _load_chunk_index(ds_dir)
            for ev in _read_events(ds_dir):
                cid = ev.get("chunk_id", "")
                meta = chunk_index.get(cid, {})
                ev["_budget"] = budget_dir.name
                ev["_dataset"] = ds_dir.name
                ev["_image_pixels"] = meta.get("image_pixels", 0)
                ev["_chunk_pixels"] = meta.get("chunk_pixels", 0)
                ev["_file_name"] = meta.get("file_name", "")
                all_events.append(ev)

    if not all_events:
        print("no events found")
        return 0

    print(f"total events: {len(all_events)}")
    by_status: Counter = Counter(e["status"] for e in all_events)
    print("by status:", dict(by_status))

    # Per status: elapsed and pixel distribution
    print("\nelapsed_ms by status (p50/p95/max):")
    for status in sorted(by_status):
        subset = [e for e in all_events if e["status"] == status]
        elapsed = [int(e.get("elapsed_ms", 0)) for e in subset]
        print(
            f"  {status:<18} n={len(subset):<3} p50={_percentile(elapsed, 50):<7} "
            f"p95={_percentile(elapsed, 95):<7} max={max(elapsed):<7}"
        )

    print("\nfail rate by chunk_pixels bucket:")
    bucket_total: Counter = Counter()
    bucket_fail: Counter = Counter()
    for e in all_events:
        b = _bucket_pixels(int(e.get("_chunk_pixels", 0)))
        bucket_total[b] += 1
        if e["status"] != "ok":
            bucket_fail[b] += 1
    for b in ["<4M", "4-6M", "6-8M", ">=8M"]:
        total = bucket_total.get(b, 0)
        fail = bucket_fail.get(b, 0)
        rate = (fail / total * 100) if total else 0
        print(f"  {b:<6} total={total:<3} fail={fail:<3} rate={rate:5.1f}%")

    print("\nfail rate by image_pixels bucket:")
    img_buckets = [
        ("<10M", 0, 10_000_000),
        ("10-20M", 10_000_000, 20_000_000),
        ("20-30M", 20_000_000, 30_000_000),
        (">=30M", 30_000_000, 10**12),
    ]
    for label, lo, hi in img_buckets:
        subset = [e for e in all_events if lo <= int(e.get("_image_pixels", 0)) < hi]
        fail = sum(1 for e in subset if e["status"] != "ok")
        rate = (fail / len(subset) * 100) if subset else 0
        print(f"  {label:<7} total={len(subset):<3} fail={fail:<3} rate={rate:5.1f}%")

    print("\nfail rate by retry_index:")
    retry_total: Counter = Counter()
    retry_fail: Counter = Counter()
    for e in all_events:
        ri = int(e.get("retry_index", 0))
        retry_total[ri] += 1
        if e["status"] != "ok":
            retry_fail[ri] += 1
    for ri in sorted(retry_total):
        total = retry_total[ri]
        fail = retry_fail[ri]
        rate = (fail / total * 100) if total else 0
        print(f"  retry_index={ri} total={total:<3} fail={fail:<3} rate={rate:5.1f}%")

    print("\nfail rate by user_id:")
    u_total: Counter = Counter()
    u_fail: Counter = Counter()
    for e in all_events:
        u = e.get("user_id") or "(unknown)"
        u_total[u] += 1
        if e["status"] != "ok":
            u_fail[u] += 1
    for u in sorted(u_total):
        total = u_total[u]
        fail = u_fail[u]
        rate = (fail / total * 100) if total else 0
        print(f"  {u:<14} total={total:<3} fail={fail:<3} rate={rate:5.1f}%")

    print("\nper-file outcome (ok/total):")
    f_total: Counter = Counter()
    f_ok: Counter = Counter()
    f_pixels: dict[str, int] = {}
    for e in all_events:
        fn = e.get("_file_name", "?")
        f_total[fn] += 1
        if e["status"] == "ok":
            f_ok[fn] += 1
        f_pixels[fn] = int(e.get("_image_pixels", 0))
    for fn in sorted(f_total, key=lambda k: -f_total[k]):
        print(
            f"  {fn[:40]:<40} chunks={f_total[fn]:<2} ok={f_ok[fn]:<2} "
            f"px={f_pixels.get(fn, 0):>10}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
