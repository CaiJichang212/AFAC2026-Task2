from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def html_table_stats(markdown: str) -> dict[str, int]:
    return {
        "tr": len(re.findall(r"<tr\b", markdown, flags=re.IGNORECASE)),
        "td": len(re.findall(r"<td\b", markdown, flags=re.IGNORECASE)),
        "empty_td": len(re.findall(r"<td\b[^>]*>\s*</td>", markdown, flags=re.IGNORECASE)),
    }


def evaluate_predictions(
    pred_dir: Path,
    gt_dir: Path,
    mapping_csv: Path | None = None,
    output: Path | None = None,
) -> dict[str, object]:
    pred_dir = Path(pred_dir)
    gt_dir = Path(gt_dir)
    mapping = _load_mapping(mapping_csv) if mapping_csv else {}
    files = []
    missing_gt: list[str] = []

    for pred_path in sorted(pred_dir.glob("*.md"), key=lambda p: p.name):
        gt_name = mapping.get(pred_path.name) or mapping.get(pred_path.stem) or pred_path.name
        gt_path = gt_dir / gt_name
        if not gt_path.exists():
            missing_gt.append(pred_path.name)
            continue
        pred_text = pred_path.read_text(encoding="utf-8")
        gt_text = gt_path.read_text(encoding="utf-8")
        distance = edit_distance(pred_text, gt_text)
        normalized = distance / max(1, len(gt_text))
        pred_stats = html_table_stats(pred_text)
        gt_stats = html_table_stats(gt_text)
        files.append(
            {
                "file_name": pred_path.name,
                "gt_file": gt_path.name,
                "edit_distance": distance,
                "normalized_edit_distance": normalized,
                "length_ratio": len(pred_text) / max(1, len(gt_text)),
                "table_pred": pred_stats,
                "table_gt": gt_stats,
                "table_diff": {key: pred_stats[key] - gt_stats[key] for key in pred_stats},
            }
        )

    mean = sum(item["normalized_edit_distance"] for item in files) / len(files) if files else 0.0
    result: dict[str, object] = {
        "file_count": len(files),
        "missing_gt": missing_gt,
        "mean_normalized_edit_distance": mean,
        "files": files,
    }
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _load_mapping(mapping_csv: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with Path(mapping_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uuid = (row.get("uuid") or "").strip()
            afts_id = (row.get("afts_id") or "").strip()
            if not uuid:
                continue
            gt_name = f"{uuid}.md"
            mapping[uuid] = gt_name
            mapping[f"{uuid}.md"] = gt_name
            if afts_id:
                mapping[afts_id] = gt_name
                mapping[f"{afts_id}.md"] = gt_name
                mapping[f"{afts_id}.jpg"] = gt_name
                mapping[f"{afts_id}.png"] = gt_name
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate local Markdown predictions against AFAC Task2 GT")
    parser.add_argument("--pred_dir", required=True)
    parser.add_argument("--gt_dir", required=True)
    parser.add_argument("--mapping_csv")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    evaluate_predictions(
        Path(args.pred_dir),
        Path(args.gt_dir),
        Path(args.mapping_csv) if args.mapping_csv else None,
        Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
