from __future__ import annotations

import hashlib
import re

from rapidfuzz.distance import Levenshtein

_LIST_RE = re.compile(r"^(\d+[.)]|[-*+])\s")


def _kind(stripped: str) -> str:
    if stripped.startswith("#"):
        return "h"
    if stripped.startswith("<table") or stripped.startswith("|"):
        return "t"
    if _LIST_RE.match(stripped):
        return "l"
    return "p"


def split_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    signatures = []
    for raw_block in re.split(r"\n\s*\n", text):
        stripped = raw_block.strip()
        if not stripped:
            continue
        normalized = re.sub(r"\s+", " ", stripped)
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
        signatures.append(f"{_kind(stripped)}:{digest}")
    return signatures


def read_order_edit(pred: str, gt: str) -> float:
    pred_blocks = split_blocks(pred)
    gt_blocks = split_blocks(gt)
    if pred_blocks == gt_blocks:
        return 0.0
    distance = Levenshtein.distance(pred_blocks, gt_blocks)
    return distance / max(1, len(gt_blocks))
