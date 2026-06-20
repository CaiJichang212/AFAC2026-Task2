from __future__ import annotations

import csv
import sys
from pathlib import Path


def _raise_csv_field_limit() -> None:
    # ground_truth 字段为整篇 Markdown，可能超过 csv 默认 131072 上限。
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            break
        except OverflowError:
            limit //= 2


_raise_csv_field_limit()


def _read_submission_csv(path) -> dict[str, str]:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        if fields is None or "file_name" not in fields or "ground_truth" not in fields:
            raise ValueError(f"CSV must have columns file_name,ground_truth: {path}")
        result: dict[str, str] = {}
        for row in reader:
            name = (row.get("file_name") or "").strip()
            if not name:
                continue
            result[name] = row.get("ground_truth") or ""
    return result


def _load_mapping(mapping_csv) -> dict[str, str]:
    path = Path(mapping_csv)
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            uuid = (row.get("uuid") or "").strip()
            if not uuid:
                continue
            afts_id = (row.get("afts_id") or "").strip()
            gt_name = f"{uuid}.md"
            mapping[uuid] = gt_name
            mapping[f"{uuid}.md"] = gt_name
            if afts_id:
                mapping[afts_id] = gt_name
                mapping[f"{afts_id}.md"] = gt_name
                mapping[f"{afts_id}.png"] = gt_name
                mapping[f"{afts_id}.jpg"] = gt_name
    return mapping


def load_pairs(
    pred_path,
    gt_path,
    mapping_csv=None,
) -> tuple[list[tuple[str, str, str]], list[str], list[str]]:
    pred = _read_submission_csv(pred_path)
    gt_path = Path(gt_path)

    pairs: list[tuple[str, str, str]] = []
    missing_gt: list[str] = []

    if gt_path.is_dir():
        mapping = _load_mapping(mapping_csv) if mapping_csv is not None else {}
        for name in sorted(pred):
            stem = Path(name).stem
            gt_name = mapping.get(name) or mapping.get(stem) or f"{stem}.md"
            gt_file = gt_path / gt_name
            if gt_file.exists():
                gt_text = gt_file.read_text(encoding="utf-8")
                pairs.append((name, pred[name], gt_text))
            else:
                missing_gt.append(name)
        return pairs, missing_gt, []

    gt = _read_submission_csv(gt_path)
    for name in sorted(pred):
        if name in gt:
            pairs.append((name, pred[name], gt[name]))
        else:
            missing_gt.append(name)
    missing_pred = sorted(set(gt) - set(pred))
    return pairs, missing_gt, missing_pred
