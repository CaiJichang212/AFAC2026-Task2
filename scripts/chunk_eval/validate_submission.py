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


def validate_submission(path: Path, expected_count: int | None = None) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["file_name", "ground_truth"]:
            raise ValueError(f"CSV columns must be exactly file_name,ground_truth: {path}")
        rows = list(reader)

    names = [(row.get("file_name") or "").strip() for row in rows]
    counts = Counter(names)
    duplicates = sorted(name for name, count in counts.items() if name and count > 1)
    empty_names = sum(1 for name in names if not name)
    empty_outputs = sum(1 for row in rows if not (row.get("ground_truth") or "").strip())

    risks: list[str] = []
    if expected_count is not None and len(rows) != expected_count:
        risks.append("row_count_mismatch")
    if duplicates:
        risks.append("duplicate_file_names")
    if empty_names:
        risks.append("empty_file_names")

    return {
        "passed": not risks,
        "rows": len(rows),
        "expected_count": expected_count,
        "duplicate_file_names": duplicates,
        "empty_file_names": empty_names,
        "empty_outputs": empty_outputs,
        "risks": risks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate AFAC Task2 submission CSV")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--expected_count", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = validate_submission(args.csv, args.expected_count)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
