from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from finix_restore.profiler import ImageProfiler
from finix_restore.quality_gate import IMAGE_SUFFIXES


FIELDNAMES = [
    "subset",
    "file_name",
    "width",
    "height",
    "pixels",
    "aspect",
    "doc_type",
    "risk_level",
    "pixel_bucket",
]


def _list_images(path: Path) -> list[Path]:
    return sorted(
        [p for p in Path(path).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES],
        key=lambda p: p.name,
    )


def _bucket_labels(count: int) -> list[str]:
    if count <= 0:
        return []
    labels: list[str] = []
    for index in range(count):
        pct_low = int((index / count) * 100)
        pct_high = int(((index + 1) / count) * 100)
        labels.append(f"p{pct_low:03d}_p{pct_high:03d}")
    return labels


def build_profiles(subset_dirs: dict[str, Path]) -> list[dict[str, str | int]]:
    profiler = ImageProfiler()
    raw_rows: list[dict[str, str | int | float]] = []
    for subset, directory in subset_dirs.items():
        for image_path in _list_images(directory):
            profile = profiler.profile(image_path)
            raw_rows.append(
                {
                    "subset": subset,
                    "file_name": profile.file_name,
                    "width": profile.width,
                    "height": profile.height,
                    "pixels": profile.pixels,
                    "aspect": profile.aspect,
                    "doc_type": profile.doc_type,
                    "risk_level": profile.risk_level,
                }
            )

    ordered = sorted(
        raw_rows,
        key=lambda row: (int(row["pixels"]), str(row["subset"]), str(row["file_name"])),
    )
    labels = _bucket_labels(len(ordered))
    bucket_by_key = {
        (row["subset"], row["file_name"]): labels[index]
        for index, row in enumerate(ordered)
    }

    result: list[dict[str, str | int]] = []
    for row in sorted(raw_rows, key=lambda item: (str(item["subset"]), str(item["file_name"]))):
        result.append(
            {
                "subset": str(row["subset"]),
                "file_name": str(row["file_name"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "pixels": int(row["pixels"]),
                "aspect": f"{float(row['aspect']):.4f}",
                "doc_type": str(row["doc_type"]),
                "risk_level": str(row["risk_level"]),
                "pixel_bucket": bucket_by_key[(row["subset"], row["file_name"])],
            }
        )
    return result


def write_profile_outputs(rows: list[dict[str, str | int]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = out_dir / "train_profile.csv"
    with profile_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    counters: Counter[tuple[str, str, str, str]] = Counter()
    for row in rows:
        counters[
            (
                str(row["subset"]),
                str(row["doc_type"]),
                str(row["risk_level"]),
                str(row["pixel_bucket"]),
            )
        ] += 1

    summary_path = out_dir / "bucket_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["subset", "doc_type", "risk_level", "pixel_bucket", "files"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for key, count in sorted(counters.items()):
            subset, doc_type, risk_level, pixel_bucket = key
            writer.writerow(
                {
                    "subset": subset,
                    "doc_type": doc_type,
                    "risk_level": risk_level,
                    "pixel_bucket": pixel_bucket,
                    "files": count,
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile AFAC Task2 train images for chunking experiments")
    parser.add_argument("--long_dir", required=True, type=Path)
    parser.add_argument("--table_dir", required=True, type=Path)
    parser.add_argument("--out_dir", required=True, type=Path)
    args = parser.parse_args(argv)

    rows = build_profiles({"long": args.long_dir, "table": args.table_dir})
    write_profile_outputs(rows, args.out_dir)
    print(f"wrote {len(rows)} profile rows -> {args.out_dir / 'train_profile.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
