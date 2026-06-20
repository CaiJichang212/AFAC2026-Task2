from __future__ import annotations

from rapidfuzz.distance import Levenshtein


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        # Collapse runs of spaces/tabs (not across newlines) into a single space.
        collapsed = []
        prev_ws = False
        for ch in line:
            if ch in (" ", "\t"):
                if not prev_ws:
                    collapsed.append(" ")
                prev_ws = True
            else:
                collapsed.append(ch)
                prev_ws = False
        lines.append("".join(collapsed).strip())
    return "\n".join(lines).strip()


def text_edit(pred: str, gt: str) -> float:
    pred_norm = normalize_text(pred)
    gt_norm = normalize_text(gt)
    if pred_norm == gt_norm:
        return 0.0
    distance = Levenshtein.distance(pred_norm, gt_norm)
    return distance / max(1, len(gt_norm))
