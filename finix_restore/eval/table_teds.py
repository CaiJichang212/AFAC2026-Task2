from __future__ import annotations

from apted import APTED, Config

from finix_restore.eval.tables import TableNode, extract_tables


class _TableConfig(Config):
    def rename(self, node_a: TableNode, node_b: TableNode) -> float:
        if node_a.tag != node_b.tag:
            return 1.0
        if node_a.tag == "td":
            same = (
                node_a.text == node_b.text
                and node_a.colspan == node_b.colspan
                and node_a.rowspan == node_b.rowspan
            )
            return 0.0 if same else 1.0
        return 0.0

    def children(self, node: TableNode):
        return node.children


def _tree_size(node: TableNode) -> int:
    return 1 + sum(_tree_size(child) for child in node.children)


# 超过该节点数的表改用近似法，避免 APTED 在超大表上的高耗时。
LARGE_TABLE_NODE_THRESHOLD = 800


def _cell_signatures(tree: TableNode) -> list[str]:
    signatures: list[str] = []
    for row in tree.children:
        for cell in row.children:
            signatures.append(f"{cell.text}|{cell.colspan}|{cell.rowspan}")
    return signatures


def _seq_levenshtein(seq_a: list[str], seq_b: list[str]) -> int:
    # 较短序列放内层，降低 DP 内层循环规模。
    if len(seq_a) < len(seq_b):
        seq_a, seq_b = seq_b, seq_a
    prev = list(range(len(seq_b) + 1))
    for i, a in enumerate(seq_a, start=1):
        curr = [i]
        for j, b in enumerate(seq_b, start=1):
            cost = 0 if a == b else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _approx_teds(pred_tree: TableNode, gt_tree: TableNode) -> float:
    pred_seq = _cell_signatures(pred_tree)
    gt_seq = _cell_signatures(gt_tree)
    if not pred_seq and not gt_seq:
        return 100.0
    distance = _seq_levenshtein(pred_seq, gt_seq)
    loss = distance / max(1, max(len(pred_seq), len(gt_seq)))
    return (1 - loss) * 100


def _single_teds(pred_tree: TableNode, gt_tree: TableNode) -> float:
    max_size = max(_tree_size(pred_tree), _tree_size(gt_tree))
    if max_size == 0:
        return 100.0
    if max_size > LARGE_TABLE_NODE_THRESHOLD:
        return _approx_teds(pred_tree, gt_tree)
    distance = APTED(pred_tree, gt_tree, _TableConfig()).compute_edit_distance()
    return (1 - distance / max_size) * 100


def has_any_table(pred: str, gt: str) -> bool:
    return bool(extract_tables(pred)) or bool(extract_tables(gt))


def table_teds(pred: str, gt: str) -> float | None:
    pred_tables = extract_tables(pred)
    gt_tables = extract_tables(gt)
    if not pred_tables and not gt_tables:
        return None

    scores: list[float] = []
    count = max(len(pred_tables), len(gt_tables))
    for i in range(count):
        if i < len(pred_tables) and i < len(gt_tables):
            scores.append(_single_teds(pred_tables[i], gt_tables[i]))
        else:
            scores.append(0.0)
    return sum(scores) / len(scores)
