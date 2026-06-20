# 官方对齐的离线自动化评测系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个与赛题线上口径对齐的离线评测系统，从预测/GT CSV 复现 Overall 三项指标（Text Edit、Table TEDS、Read Order Edit）与综合得分。

**Architecture:** 在 `finix_restore/eval/` 下新建独立评测包，按职责拆分小模块（io / text_metric / tables / table_teds / reading_order / scorer / cli），每个文件单一职责、可独立单测；不改动主 pipeline 与现有 `local_eval.py`。

**Tech Stack:** Python 3，`apted`（树编辑距离，新增依赖），`beautifulsoup4`/`lxml`（HTML 表格解析，已有），`pytest`（已有）。

---

## 文件结构

- 新建 `finix_restore/eval/__init__.py` —— 导出公共入口（`evaluate`, `score_pair`）。
- 新建 `finix_restore/eval/text_metric.py` —— Text Edit：文本归一化 + 字级 Levenshtein 归一化。
- 新建 `finix_restore/eval/tables.py` —— 表格抽取（HTML `<table>` + Markdown pipe→HTML）并解析为树节点。
- 新建 `finix_restore/eval/table_teds.py` —— 基于 `apted` 的 TEDS 得分。
- 新建 `finix_restore/eval/reading_order.py` —— Read Order Edit：逻辑块切分 + 块级 Levenshtein 归一化。
- 新建 `finix_restore/eval/io.py` —— 读取预测/GT（CSV 或 id_mapping+mds 目录），对齐成 (file_name, pred, gt) 三元组。
- 新建 `finix_restore/eval/scorer.py` —— 合成 Overall，聚合每文件明细 + 数据集汇总，写 JSON。
- 新建 `finix_restore/eval/cli.py` —— 命令行入口。
- 新建测试：`tests/test_eval_text_metric.py`、`tests/test_eval_tables.py`、`tests/test_eval_table_teds.py`、`tests/test_eval_reading_order.py`、`tests/test_eval_io.py`、`tests/test_eval_scorer.py`、`tests/test_eval_cli.py`。
- 修改 `requirements.txt` —— 新增 `apted`。

---

## Task 1: 新增 apted 依赖与 eval 包骨架

**Files:**
- Modify: `requirements.txt`
- Create: `finix_restore/eval/__init__.py`

- [ ] **Step 1: 在 requirements.txt 末尾新增 apted**

`requirements.txt` 当前内容为（pillow/numpy/pandas/requests/python-dotenv/PyYAML/beautifulsoup4/lxml/pytest/ruff）。在文件末尾追加一行：

```
apted
```

- [ ] **Step 2: 安装依赖**

Run: `pip install apted`
Expected: 成功安装 apted（纯 Python，无编译）。

- [ ] **Step 3: 创建空的包初始化文件**

创建 `finix_restore/eval/__init__.py`，内容为：

```python
from __future__ import annotations

# Public API is wired up in later tasks (scorer.evaluate, scorer.score_pair).
```

- [ ] **Step 4: 验证包可导入**

Run: `python -c "import finix_restore.eval"`
Expected: 无输出、退出码 0。

- [ ] **Step 5: 提交**

```bash
git add requirements.txt finix_restore/eval/__init__.py
git commit -m "chore: add apted dep and eval package skeleton"
```

---

## Task 2: Text Edit 指标

**Files:**
- Create: `finix_restore/eval/text_metric.py`
- Test: `tests/test_eval_text_metric.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_text_metric.py`：

```python
from finix_restore.eval.text_metric import normalize_text, text_edit


def test_normalize_collapses_whitespace_and_strips():
    assert normalize_text("  a\r\nb \t c \n") == "a\nb c"


def test_text_edit_identical_is_zero():
    assert text_edit("abc", "abc") == 0.0


def test_text_edit_one_substitution_normalized_by_gt_length():
    # gt="abxd" len=4, pred="abcd" -> 1 substitution -> 1/4
    assert text_edit("abcd", "abxd") == 0.25


def test_text_edit_empty_gt_uses_len_one_denominator():
    assert text_edit("a", "") == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_text_metric.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.text_metric）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/text_metric.py`：

```python
from __future__ import annotations

import re


def _levenshtein(a: str, b: str) -> int:
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


def normalize_text(text: str) -> str:
    # 统一换行，将连续空白（不含换行结构）压缩为单空格，逐行去首尾空白后去整体首尾空白。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", line).strip()
        lines.append(line)
    return "\n".join(lines).strip()


def text_edit(pred: str, gt: str) -> float:
    pred_n = normalize_text(pred)
    gt_n = normalize_text(gt)
    distance = _levenshtein(pred_n, gt_n)
    return distance / max(1, len(gt_n))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_text_metric.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/text_metric.py tests/test_eval_text_metric.py
git commit -m "feat(eval): add Text Edit normalized levenshtein metric"
```

---

## Task 3: 表格抽取与树构建

**Files:**
- Create: `finix_restore/eval/tables.py`
- Test: `tests/test_eval_tables.py`

说明：GT 表格主要是 HTML `<table>`（含 `rowspan`/`colspan`），少量可能是 Markdown pipe 表格。本任务把两种形态统一抽取为 `TableNode` 树，供 TEDS 使用。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_tables.py`：

```python
from finix_restore.eval.tables import extract_tables, TableNode


def test_extract_html_table_builds_tree_with_spans():
    md = (
        "intro\n"
        "<table><tr><td rowspan=\"2\">A</td><td colspan=\"2\">B</td></tr>"
        "<tr><td>C</td><td>D</td></tr></table>\n"
        "outro"
    )
    trees = extract_tables(md)
    assert len(trees) == 1
    root = trees[0]
    assert isinstance(root, TableNode)
    assert root.tag == "table"
    assert len(root.children) == 2  # two rows
    first_row = root.children[0]
    assert first_row.tag == "tr"
    assert first_row.children[0].tag == "td"
    assert first_row.children[0].text == "A"
    assert first_row.children[0].rowspan == 2
    assert first_row.children[1].colspan == 2


def test_extract_markdown_pipe_table_converted_to_tree():
    md = "| h1 | h2 |\n|---|---|\n| a | b |\n"
    trees = extract_tables(md)
    assert len(trees) == 1
    root = trees[0]
    assert root.tag == "table"
    # header row + body row
    assert len(root.children) == 2
    assert root.children[0].children[0].text == "h1"
    assert root.children[1].children[1].text == "b"


def test_no_table_returns_empty_list():
    assert extract_tables("# title\nplain paragraph") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_tables.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.tables）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/tables.py`：

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup


@dataclass
class TableNode:
    tag: str
    text: str = ""
    colspan: int = 1
    rowspan: int = 1
    children: list["TableNode"] = field(default_factory=list)


def _cell_node(cell) -> TableNode:
    def _span(attr: str) -> int:
        try:
            return max(1, int(cell.get(attr, "1")))
        except (TypeError, ValueError):
            return 1

    text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
    return TableNode(tag="td", text=text, colspan=_span("colspan"), rowspan=_span("rowspan"))


def _html_table_to_node(table) -> TableNode:
    root = TableNode(tag="table")
    for row in table.find_all("tr"):
        row_node = TableNode(tag="tr")
        for cell in row.find_all(["td", "th"]):
            row_node.children.append(_cell_node(cell))
        root.children.append(row_node)
    return root


def _markdown_tables_to_html(markdown: str) -> list[str]:
    html_tables: list[str] = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        is_row = line.startswith("|") and line.endswith("|")
        sep = i + 1 < len(lines) and re.fullmatch(r"\|[:\- |]+\|", lines[i + 1].strip() or "")
        if is_row and sep:
            block = [lines[i].strip(), lines[i + 1].strip()]
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j].strip())
                j += 1
            html_tables.append(_one_markdown_table_to_html(block))
            i = j
        else:
            i += 1
    return html_tables


def _split_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _one_markdown_table_to_html(block: list[str]) -> str:
    header = _split_cells(block[0])
    body_rows = [_split_cells(r) for r in block[2:]]
    rows_html = ["<tr>" + "".join(f"<td>{c}</td>" for c in header) + "</tr>"]
    for row in body_rows:
        rows_html.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    return "<table>" + "".join(rows_html) + "</table>"


def extract_tables(markdown: str) -> list[TableNode]:
    nodes: list[TableNode] = []
    soup = BeautifulSoup(markdown, "lxml")
    for table in soup.find_all("table"):
        nodes.append(_html_table_to_node(table))
    for html in _markdown_tables_to_html(markdown):
        sub = BeautifulSoup(html, "lxml")
        table = sub.find("table")
        if table is not None:
            nodes.append(_html_table_to_node(table))
    return nodes
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_tables.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/tables.py tests/test_eval_tables.py
git commit -m "feat(eval): extract HTML and markdown tables into node trees"
```

---

## Task 4: Table TEDS 指标

**Files:**
- Create: `finix_restore/eval/table_teds.py`
- Test: `tests/test_eval_table_teds.py`

说明：用 `apted` 计算两棵 `TableNode` 树的编辑距离，按 TEDS 标准归一化为 [0,100]。`has_table` 用于上层判断该样本是否计入 Table TEDS 均值。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_table_teds.py`：

```python
from finix_restore.eval.table_teds import table_teds, has_any_table


def test_identical_tables_score_100():
    md = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    score = table_teds(md, md)
    assert score == 100.0


def test_cell_text_difference_lowers_score():
    pred = "<table><tr><td>A</td><td>X</td></tr></table>"
    gt = "<table><tr><td>A</td><td>B</td></tr></table>"
    score = table_teds(pred, gt)
    assert 0.0 < score < 100.0


def test_both_without_table_returns_none():
    assert table_teds("plain text", "plain text") is None


def test_has_any_table_detection():
    assert has_any_table("<table><tr><td>A</td></tr></table>", "no table") is True
    assert has_any_table("none", "none") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_table_teds.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.table_teds）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/table_teds.py`：

```python
from __future__ import annotations

from apted import APTED, Config

from finix_restore.eval.tables import TableNode, extract_tables


class _TableConfig(Config):
    def rename(self, node_a: TableNode, node_b: TableNode) -> int:
        if node_a.tag != node_b.tag:
            return 1
        if node_a.tag == "td":
            same = (
                node_a.text == node_b.text
                and node_a.colspan == node_b.colspan
                and node_a.rowspan == node_b.rowspan
            )
            return 0 if same else 1
        return 0

    def children(self, node: TableNode):
        return node.children


def _tree_size(node: TableNode) -> int:
    return 1 + sum(_tree_size(child) for child in node.children)


def _single_teds(pred_tree: TableNode, gt_tree: TableNode) -> float:
    distance = APTED(pred_tree, gt_tree, _TableConfig()).compute_edit_distance()
    denom = max(_tree_size(pred_tree), _tree_size(gt_tree))
    if denom == 0:
        return 100.0
    return (1.0 - distance / denom) * 100.0


def has_any_table(pred: str, gt: str) -> bool:
    return bool(extract_tables(pred)) or bool(extract_tables(gt))


def table_teds(pred: str, gt: str) -> float | None:
    pred_tables = extract_tables(pred)
    gt_tables = extract_tables(gt)
    if not pred_tables and not gt_tables:
        return None
    count = max(len(pred_tables), len(gt_tables))
    scores: list[float] = []
    for idx in range(count):
        if idx < len(pred_tables) and idx < len(gt_tables):
            scores.append(_single_teds(pred_tables[idx], gt_tables[idx]))
        else:
            scores.append(0.0)
    return sum(scores) / len(scores)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_table_teds.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/table_teds.py tests/test_eval_table_teds.py
git commit -m "feat(eval): add Table TEDS metric via apted tree edit distance"
```

---

## Task 5: Read Order Edit 指标

**Files:**
- Create: `finix_restore/eval/reading_order.py`
- Test: `tests/test_eval_reading_order.py`

说明：将文本切分为逻辑块（标题 / 表格 / 列表 / 段落，以空行分隔），每块生成稳定的身份签名 token，对 token 序列做 Levenshtein 归一化。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_reading_order.py`：

```python
from finix_restore.eval.reading_order import split_blocks, read_order_edit


def test_split_blocks_separates_headings_and_paragraphs():
    text = "# Title\n\npara one\n\n## Sub\n\npara two"
    blocks = split_blocks(text)
    assert len(blocks) == 4
    assert blocks[0].startswith("h:")
    assert blocks[1].startswith("p:")
    assert blocks[2].startswith("h:")


def test_identical_order_is_zero():
    text = "# A\n\nbody a\n\n# B\n\nbody b"
    assert read_order_edit(text, text) == 0.0


def test_swapped_blocks_increase_distance():
    gt = "# A\n\nbody a\n\n# B\n\nbody b"
    pred = "# B\n\nbody b\n\n# A\n\nbody a"
    score = read_order_edit(pred, gt)
    assert score > 0.0


def test_empty_gt_uses_len_one_denominator():
    assert read_order_edit("# A\n\nbody", "") == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_reading_order.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.reading_order）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/reading_order.py`：

```python
from __future__ import annotations

import hashlib
import re


def _block_signature(block: str) -> str:
    stripped = block.strip()
    if stripped.startswith("#"):
        kind = "h"
    elif stripped.startswith("<table") or stripped.startswith("|"):
        kind = "t"
    elif re.match(r"^(\d+[.)]|[-*+])\s", stripped):
        kind = "l"
    else:
        kind = "p"
    norm = re.sub(r"\s+", " ", stripped)
    digest = hashlib.md5(norm.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def split_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [_block_signature(b) for b in raw_blocks]


def _seq_levenshtein(a: list[str], b: list[str]) -> int:
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


def read_order_edit(pred: str, gt: str) -> float:
    pred_blocks = split_blocks(pred)
    gt_blocks = split_blocks(gt)
    distance = _seq_levenshtein(pred_blocks, gt_blocks)
    return distance / max(1, len(gt_blocks))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_reading_order.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/reading_order.py tests/test_eval_reading_order.py
git commit -m "feat(eval): add Read Order Edit block-level metric"
```

---

## Task 6: 输入读取与对齐（io）

**Files:**
- Create: `finix_restore/eval/io.py`
- Test: `tests/test_eval_io.py`

说明：预测与 GT 支持官方 CSV（`file_name`, `ground_truth`）；GT 还支持训练集 `id_mapping.csv + mds/` 目录。输出对齐三元组与缺失项列表。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_io.py`：

```python
from finix_restore.eval.io import load_pairs


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_load_pairs_from_two_csv(tmp_path):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    _write(pred, "file_name,ground_truth\ndoc_001.png,hello\ndoc_002.png,world\n")
    _write(gt, "file_name,ground_truth\ndoc_001.png,hi\ndoc_002.png,world\n")

    pairs, missing_gt, missing_pred = load_pairs(pred, gt)

    assert {p[0] for p in pairs} == {"doc_001.png", "doc_002.png"}
    assert dict((p[0], (p[1], p[2])) for p in pairs)["doc_001.png"] == ("hello", "hi")
    assert missing_gt == []
    assert missing_pred == []


def test_missing_gt_and_pred_are_reported(tmp_path):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    _write(pred, "file_name,ground_truth\na.png,pa\nb.png,pb\n")
    _write(gt, "file_name,ground_truth\na.png,ga\nc.png,gc\n")

    pairs, missing_gt, missing_pred = load_pairs(pred, gt)

    assert [p[0] for p in pairs] == ["a.png"]
    assert missing_gt == ["b.png"]   # in pred but no gt
    assert missing_pred == ["c.png"]  # in gt but no pred


def test_gt_from_mapping_directory(tmp_path):
    pred = tmp_path / "pred.csv"
    _write(pred, "file_name,ground_truth\nafts-1.png,pred-text\n")
    gt_dir = tmp_path / "mds"
    gt_dir.mkdir()
    _write(gt_dir / "uuid-1.md", "gt-text")
    mapping = tmp_path / "id_mapping.csv"
    _write(mapping, "uuid,afts_id\nuuid-1,afts-1\n")

    pairs, missing_gt, missing_pred = load_pairs(pred, gt_dir, mapping_csv=mapping)

    assert pairs == [("afts-1.png", "pred-text", "gt-text")]
    assert missing_gt == []
    assert missing_pred == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_io.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.io）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/io.py`：

```python
from __future__ import annotations

import csv
from pathlib import Path


def _read_submission_csv(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "file_name" not in reader.fieldnames or "ground_truth" not in reader.fieldnames:
            raise ValueError(f"CSV must have columns file_name,ground_truth: {path}")
        for row in reader:
            name = (row.get("file_name") or "").strip()
            if name:
                rows[name] = row.get("ground_truth") or ""
    return rows


def _load_mapping(mapping_csv: Path) -> dict[str, str]:
    # Map any of {uuid, uuid.md, afts_id, afts_id.*} -> gt md filename (uuid.md)
    mapping: dict[str, str] = {}
    with Path(mapping_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uuid = (row.get("uuid") or "").strip()
            afts = (row.get("afts_id") or "").strip()
            if not uuid:
                continue
            gt_name = f"{uuid}.md"
            mapping[uuid] = gt_name
            mapping[f"{uuid}.md"] = gt_name
            if afts:
                for key in (afts, f"{afts}.md", f"{afts}.png", f"{afts}.jpg"):
                    mapping[key] = gt_name
    return mapping


def load_pairs(
    pred_path,
    gt_path,
    mapping_csv=None,
):
    pred_path = Path(pred_path)
    gt_path = Path(gt_path)
    pred_rows = _read_submission_csv(pred_path)

    if gt_path.is_dir():
        mapping = _load_mapping(mapping_csv) if mapping_csv else {}

        def gt_lookup(name: str) -> str | None:
            gt_name = mapping.get(name) or mapping.get(Path(name).stem) or f"{Path(name).stem}.md"
            gt_file = gt_path / gt_name
            if gt_file.exists():
                return gt_file.read_text(encoding="utf-8")
            return None

        gt_names = None
    else:
        gt_rows = _read_submission_csv(gt_path)

        def gt_lookup(name: str) -> str | None:
            return gt_rows.get(name)

        gt_names = set(gt_rows.keys())

    pairs: list[tuple[str, str, str]] = []
    missing_gt: list[str] = []
    for name in sorted(pred_rows):
        gt_text = gt_lookup(name)
        if gt_text is None:
            missing_gt.append(name)
            continue
        pairs.append((name, pred_rows[name], gt_text))

    missing_pred: list[str] = []
    if gt_names is not None:
        missing_pred = sorted(gt_names - set(pred_rows.keys()))

    return pairs, missing_gt, missing_pred
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_io.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/io.py tests/test_eval_io.py
git commit -m "feat(eval): load and align prediction/GT pairs from csv or mds dir"
```

---

## Task 7: Scorer 合成 Overall

**Files:**
- Create: `finix_restore/eval/scorer.py`
- Modify: `finix_restore/eval/__init__.py`
- Test: `tests/test_eval_scorer.py`

说明：逐文件计算三项指标并按官方公式合成 Overall（无表样本该文件 Table TEDS 视为 100）；数据集层面 `mean_table_teds` 仅统计含表样本。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_scorer.py`：

```python
import json

from finix_restore.eval.scorer import score_pair, evaluate


def test_score_pair_identical_is_perfect():
    text = "# A\n\nbody"
    result = score_pair("doc.png", text, text)
    assert result["text_edit"] == 0.0
    assert result["read_order_edit"] == 0.0
    assert result["table_teds"] is None
    assert result["has_table"] is False
    # no table -> table component treated as 100
    assert result["overall"] == 100.0


def test_score_pair_with_table_uses_teds_in_overall():
    text = "<table><tr><td>A</td></tr></table>"
    result = score_pair("doc.png", text, text)
    assert result["has_table"] is True
    assert result["table_teds"] == 100.0
    assert result["overall"] == 100.0


def test_evaluate_aggregates_and_writes_report(tmp_path):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    pred.write_text(
        "file_name,ground_truth\n"
        "t.png,<table><tr><td>A</td></tr></table>\n"
        "p.png,# Title\n",
        encoding="utf-8",
    )
    gt.write_text(
        "file_name,ground_truth\n"
        "t.png,<table><tr><td>A</td></tr></table>\n"
        "p.png,# Title\n",
        encoding="utf-8",
    )
    out = tmp_path / "metrics.json"

    report = evaluate(pred, gt, output=out)

    assert report["file_count"] == 2
    assert report["mean_overall"] == 100.0
    # only the table sample participates in table mean
    assert report["mean_table_teds"] == 100.0
    assert report["table_sample_count"] == 1
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["mean_overall"] == 100.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_scorer.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.scorer）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/scorer.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

from finix_restore.eval.io import load_pairs
from finix_restore.eval.reading_order import read_order_edit
from finix_restore.eval.table_teds import table_teds
from finix_restore.eval.text_metric import text_edit


def score_pair(file_name: str, pred: str, gt: str) -> dict:
    te = text_edit(pred, gt)
    roe = read_order_edit(pred, gt)
    teds = table_teds(pred, gt)
    has_table = teds is not None
    table_component = teds if has_table else 100.0
    overall = ((1.0 - te) * 100.0 + table_component + (1.0 - roe) * 100.0) / 3.0
    return {
        "file_name": file_name,
        "text_edit": te,
        "table_teds": teds,
        "read_order_edit": roe,
        "has_table": has_table,
        "overall": overall,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(pred_path, gt_path, mapping_csv=None, output=None) -> dict:
    pairs, missing_gt, missing_pred = load_pairs(pred_path, gt_path, mapping_csv)
    files = [score_pair(name, pred, gt) for name, pred, gt in pairs]

    table_scores = [f["table_teds"] for f in files if f["has_table"]]
    report = {
        "file_count": len(files),
        "missing_gt": missing_gt,
        "missing_pred": missing_pred,
        "mean_text_edit": _mean([f["text_edit"] for f in files]),
        "mean_read_order_edit": _mean([f["read_order_edit"] for f in files]),
        "mean_table_teds": _mean(table_scores),
        "table_sample_count": len(table_scores),
        "mean_overall": _mean([f["overall"] for f in files]),
        "files": files,
    }
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
```

- [ ] **Step 4: 导出公共 API**

将 `finix_restore/eval/__init__.py` 替换为：

```python
from __future__ import annotations

from finix_restore.eval.scorer import evaluate, score_pair

__all__ = ["evaluate", "score_pair"]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_eval_scorer.py -v`
Expected: 3 passed。

- [ ] **Step 6: 提交**

```bash
git add finix_restore/eval/scorer.py finix_restore/eval/__init__.py tests/test_eval_scorer.py
git commit -m "feat(eval): aggregate three metrics into official Overall score"
```

---

## Task 8: CLI 入口

**Files:**
- Create: `finix_restore/eval/cli.py`
- Test: `tests/test_eval_cli.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_cli.py`：

```python
import json

from finix_restore.eval.cli import main


def test_cli_runs_and_writes_report(tmp_path, capsys):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    pred.write_text("file_name,ground_truth\nd.png,# Title\n", encoding="utf-8")
    gt.write_text("file_name,ground_truth\nd.png,# Title\n", encoding="utf-8")
    out = tmp_path / "metrics.json"

    code = main([
        "--pred", str(pred),
        "--gt", str(gt),
        "--output", str(out),
    ])

    assert code == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["file_count"] == 1
    captured = capsys.readouterr()
    assert "Overall" in captured.out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_eval_cli.py -v`
Expected: FAIL（ModuleNotFoundError: finix_restore.eval.cli）。

- [ ] **Step 3: 实现最小代码**

创建 `finix_restore/eval/cli.py`：

```python
from __future__ import annotations

import argparse
from pathlib import Path

from finix_restore.eval.scorer import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline scorer reproducing AFAC Task2 Overall (Text Edit / Table TEDS / Read Order Edit)"
    )
    parser.add_argument("--pred", required=True, help="prediction CSV (file_name,ground_truth)")
    parser.add_argument("--gt", required=True, help="GT CSV or mds directory")
    parser.add_argument("--mapping_csv", help="id_mapping.csv when --gt is a directory")
    parser.add_argument("--output", required=True, help="metrics JSON output path")
    args = parser.parse_args(argv)

    report = evaluate(
        Path(args.pred),
        Path(args.gt),
        Path(args.mapping_csv) if args.mapping_csv else None,
        Path(args.output),
    )

    print(f"files: {report['file_count']}  table_samples: {report['table_sample_count']}")
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_eval_cli.py -v`
Expected: 1 passed。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/eval/cli.py tests/test_eval_cli.py
git commit -m "feat(eval): add scorer CLI entry point"
```

---

## Task 9: 全量验证

**Files:** 无新增。

- [ ] **Step 1: 运行全部测试**

Run: `pytest -q`
Expected: 全绿，包含新增 7 个 eval 测试文件，且原 `tests/test_local_eval.py` 等仍通过。

- [ ] **Step 2: 运行 lint**

Run: `ruff check finix_restore/eval tests`
Expected: 无错误（若有则修复后重跑）。

- [ ] **Step 3: 在训练集上真实跑通 CLI（冒烟）**

构造一份最小预测 CSV：取 `data/AFAC 训练数据集/finixdocbench_huge_table_100/mds/` 中任意 2 个 GT 作为「预测」，文件名用对应 afts_id（可直接用 uuid 作 file_name 并把 GT 也用同一 CSV）以验证流程；或直接用同一份 CSV 作为 pred 和 gt，确认 Overall≈100。

示例（自洽冒烟，确认管线打通）：

```bash
python -m finix_restore.eval.cli \
  --pred /tmp/smoke_pred.csv \
  --gt /tmp/smoke_pred.csv \
  --output outputs/eval/smoke_metrics.json
```

Expected: 打印 Overall 100.00；`outputs/eval/smoke_metrics.json` 字段完整。

- [ ] **Step 4: 最终提交（如有 lint 修复或冒烟产物清理）**

```bash
git add -A
git commit -m "test(eval): full suite green and CLI smoke verified"
```

注意：`outputs/` 仅放运行产物、不入库；如冒烟产物落在 `outputs/`，确认其在 `.gitignore` 中或不要 `git add`。
