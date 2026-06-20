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


def _single_teds(pred_tree: TableNode, gt_tree: TableNode) -> float:
    max_size = max(_tree_size(pred_tree), _tree_size(gt_tree))
    if max_size == 0:
        return 100.0
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
