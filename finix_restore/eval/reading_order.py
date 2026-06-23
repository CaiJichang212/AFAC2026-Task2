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


_TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)


def _iter_logical_units(text: str):
    """Yield logical units in reading order.

    A unit is either a complete ``<table>...</table>`` block (kept whole so that
    table-internal row differences are scored by TEDS, not Read Order) or a
    single non-empty line. Splitting per non-empty line (instead of per blank
    line) makes the metric insensitive to paragraph spacing style: GT mixes
    single-newline and blank-line separation across samples, so a blank-line
    split is not comparable across the dataset.
    """
    pos = 0
    for match in _TABLE_BLOCK_RE.finditer(text):
        before = text[pos:match.start()]
        for line in before.split("\n"):
            stripped = line.strip()
            if stripped:
                yield stripped
        yield match.group(0)
        pos = match.end()
    for line in text[pos:].split("\n"):
        stripped = line.strip()
        if stripped:
            yield stripped


def split_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    signatures = []
    for unit in _iter_logical_units(text):
        normalized = re.sub(r"\s+", " ", unit)
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
        signatures.append(f"{_kind(unit)}:{digest}")
    return signatures


def read_order_edit(pred: str, gt: str) -> float:
    pred_blocks = split_blocks(pred)
    gt_blocks = split_blocks(gt)
    if pred_blocks == gt_blocks:
        return 0.0
    distance = Levenshtein.distance(pred_blocks, gt_blocks)
    return distance / max(1, len(gt_blocks))
