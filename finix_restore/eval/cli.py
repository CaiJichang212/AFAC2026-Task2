from __future__ import annotations

import argparse
from pathlib import Path

from finix_restore.eval.scorer import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline scorer for document restoration")
    parser.add_argument("--pred", required=True, help="submission CSV path")
    parser.add_argument("--gt", required=True, help="ground truth CSV or directory")
    parser.add_argument("--mapping_csv", default=None, help="uuid/afts mapping CSV (directory mode)")
    parser.add_argument("--output", required=True, help="report JSON output path")
    args = parser.parse_args(argv)

    mapping = Path(args.mapping_csv) if args.mapping_csv else None
    report = evaluate(Path(args.pred), Path(args.gt), mapping, Path(args.output))

    print(
        f"files: {report['file_count']}  "
        f"table_samples: {report['table_sample_count']}"
    )
    print(f"mean Text Edit:       {report['mean_text_edit']:.4f}")
    print(f"mean Table TEDS:      {report['mean_table_teds']:.2f}")
    print(f"mean Read Order Edit: {report['mean_read_order_edit']:.4f}")
    print(f"Overall:              {report['mean_overall']:.2f}")

    if report["missing_gt"]:
        print(f"missing_gt: {len(report['missing_gt'])}")
    if report["missing_pred"]:
        print(f"missing_pred: {len(report['missing_pred'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
