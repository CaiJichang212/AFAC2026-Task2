from __future__ import annotations


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


def _levenshtein(a: str, b: str) -> int:
    # Keep the shorter string inner to minimize the rolling array size.
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            ))
        previous = current
    return previous[-1]


def text_edit(pred: str, gt: str) -> float:
    pred_norm = normalize_text(pred)
    gt_norm = normalize_text(gt)
    if pred_norm == gt_norm:
        return 0.0
    distance = _levenshtein(pred_norm, gt_norm)
    return distance / max(1, len(gt_norm))
