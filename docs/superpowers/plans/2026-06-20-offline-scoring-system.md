# 官方对齐的离线自动化评测系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个与赛题线上口径对齐的离线评测系统，从预测/GT CSV 复现 Overall 三项指标（Text Edit、Table TEDS、Read Order Edit）与综合得分。

**Architecture:** 在 `finix_restore/eval/` 下新建独立评测包，按职责拆分小模块（io / text_metric / tables / table_teds / reading_order / scorer / cli），每个文件单一职责、可独立单测；不改动主 pipeline 与现有 `local_eval.py`。

**Tech Stack:** Python 3，`apted`（树编辑距离，新增依赖），`beautifulsoup4`/`lxml`（HTML 表格解析，已有），`pytest`（已有）。

**评分公式（验收基准）：**

```
Overall = [ (1 - Text Edit) * 100 + Table TEDS + (1 - Read Order Edit) * 100 ] / 3
```

---

## 文件结构

| 文件 | 职责 |
|:---|:---|
| `finix_restore/eval/__init__.py` | 导出公共入口 `evaluate`, `score_pair` |
| `finix_restore/eval/text_metric.py` | Text Edit：文本归一化 + 字级 Levenshtein 归一化 |
| `finix_restore/eval/tables.py` | 表格抽取（HTML `<table>` + Markdown pipe→HTML）→ `TableNode` 树 |
| `finix_restore/eval/table_teds.py` | 基于 `apted` 的 TEDS 得分 |
| `finix_restore/eval/reading_order.py` | Read Order Edit：逻辑块切分 + 块级 Levenshtein 归一化 |
| `finix_restore/eval/io.py` | 读取预测/GT（CSV 或 id_mapping+mds 目录），对齐三元组 |
| `finix_restore/eval/scorer.py` | 合成 Overall，聚合每文件明细 + 数据集汇总，写 JSON |
| `finix_restore/eval/cli.py` | 命令行入口 |
| `tests/test_eval_*.py` | 各模块单测（每模块一个文件） |
| `requirements.txt` | 新增 `apted` |

---

## 接口契约

实现时必须严格遵守以下签名与语义；测试与下游模块据此对接。所有度量值方向：Text Edit / Read Order Edit ∈ [0,1]（越低越好），Table TEDS ∈ [0,100]（越高越好）。

**text_metric.py**
- `normalize_text(text: str) -> str`：统一 `\r\n`/`\r` 为 `\n`；逐行将连续空格/制表压为单空格并去行首尾空白；最后去整体首尾空白。
- `text_edit(pred: str, gt: str) -> float`：对归一化后的两串求字级 Levenshtein，除以 `max(1, len(gt_norm))`。相同串返回 `0.0`；gt 为空时分母取 1。

**tables.py**
- `TableNode`（dataclass）：字段 `tag: str`、`text: str=""`、`colspan: int=1`、`rowspan: int=1`、`children: list[TableNode]`。
- `extract_tables(markdown: str) -> list[TableNode]`：返回文档内全部表格树，按出现顺序；先收 HTML `<table>`，再收 Markdown pipe 表格（转 HTML 后解析）；无表返回 `[]`。单元格文本经空白归一化。

**table_teds.py**
- `has_any_table(pred: str, gt: str) -> bool`：任一侧含表即 `True`。
- `table_teds(pred: str, gt: str) -> float | None`：双方均无表返回 `None`；否则逐表按出现顺序配对，缺失配对的多余表该表得 0，取所有表得分均值。单表 TEDS 见下方公式契约。

**reading_order.py**
- `split_blocks(text: str) -> list[str]`：按空行切块，每块产出身份签名 `"{kind}:{md5前12位}"`，`kind ∈ {h(标题), t(表格), l(列表), p(段落)}`。
- `read_order_edit(pred: str, gt: str) -> float`：对两个签名序列求序列级 Levenshtein，除以 `max(1, len(gt_blocks))`。

**io.py**
- `load_pairs(pred_path, gt_path, mapping_csv=None) -> tuple[list[tuple[str,str,str]], list[str], list[str]]`
  - 返回 `(pairs, missing_gt, missing_pred)`，`pairs` 元素为 `(file_name, pred_text, gt_text)`，按 file_name 升序。
  - 预测必须是官方 CSV（列 `file_name`, `ground_truth`）；列缺失抛 `ValueError`。
  - GT 为 CSV 时同格式；GT 为目录时配合 `mapping_csv`（`uuid,afts_id`）将预测文件名映射到 `{uuid}.md`。
  - `missing_gt`：预测有而 GT 无；`missing_pred`：GT 有而预测无（仅 GT 为 CSV 时可计算，目录模式为 `[]`）。

**scorer.py**
- `score_pair(file_name: str, pred: str, gt: str) -> dict`：键含 `file_name, text_edit, table_teds(可为None), read_order_edit, has_table(bool), overall`。无表样本 `overall` 中表格分量取 100。
- `evaluate(pred_path, gt_path, mapping_csv=None, output=None) -> dict`：聚合报告，键含 `file_count, missing_gt, missing_pred, mean_text_edit, mean_read_order_edit, mean_table_teds, table_sample_count, mean_overall, files`。`mean_table_teds` 仅统计 `has_table` 为真的样本。`output` 非空时写 JSON。

**cli.py**
- `main(argv: list[str] | None = None) -> int`：参数 `--pred`（必填）、`--gt`（必填，CSV 或目录）、`--mapping_csv`（目录模式用）、`--output`（必填）。打印各项均值与 Overall，返回 0。

### 关键公式契约（易误解，固化于此）

单表 TEDS（归一化为百分制）：

```
TEDS_single = (1 - tree_edit_distance / max(size(pred_tree), size(gt_tree))) * 100
```

其中 `size` 为树的节点总数；`max(size)==0` 时记 100。APTED 的 `rename` 代价：`tag` 不同记 1；`tag=="td"` 且 `(text, colspan, rowspan)` 完全相同记 0、否则 1；其余同标签节点记 0。

---

## 决策与约束（来自设计评审）

- 输入对齐官方 CSV，同时兼容训练集 `id_mapping.csv + mds/`。
- TEDS 复用 `apted`（新增依赖），表格解析复用 bs4/lxml。
- 无表样本：`mean_table_teds` 仅含表样本参与；单文件 `overall` 中无表样本表格分量取 100（报告显式标注口径）。
- 独立评测模块 + CLI，不绑定主 pipeline；不改 `data/`、不调外部模型 API。
- GT 表格实测以 HTML `<table>`（含 `rowspan`/`colspan`）为主，Markdown pipe 为辅 —— 解析以 HTML 为主路径。

---

## 分支与 PR

- 本计划在独立分支实现（如 `feat/offline-scoring`），每个 Task 一次提交，便于回溯。
- 全部 Task 完成且 `pytest -q`、`ruff check` 通过后，发起 PR 合入；**完整实现源码以 PR diff 为准，不回填本计划文档**。
- PR 描述引用本计划与设计文档路径，列出新增模块与验收结果。

---

## Task 1: 新增 apted 依赖与 eval 包骨架

**Files:** Modify `requirements.txt`；Create `finix_restore/eval/__init__.py`

- [ ] **Step 1:** `requirements.txt` 末尾追加一行 `apted`。
- [ ] **Step 2:** 安装依赖。Run: `pip install apted`，Expected: 成功（纯 Python，无编译）。
- [ ] **Step 3:** 创建 `finix_restore/eval/__init__.py`（先留空占位，Task 7 再补导出）。
- [ ] **Step 4:** 验证可导入。Run: `python -c "import finix_restore.eval"`，Expected: 退出码 0。
- [ ] **Step 5:** 提交。`git commit -m "chore: add apted dep and eval package skeleton"`

---

## Task 2: Text Edit 指标

**Files:** Create `finix_restore/eval/text_metric.py`；Test `tests/test_eval_text_metric.py`（TDD：先写失败测试）

**实现要点：** 实现 `normalize_text` 与 `text_edit`（签名见接口契约）。Levenshtein 用标准 DP（短串做内层以省内存）。

**测试用例（验收）：**
- `normalize_text("  a\r\nb \t c \n")` == `"a\nb c"`
- `text_edit("abc","abc")` == `0.0`
- `text_edit("abcd","abxd")` == `0.25`（gt 长 4，1 次替换）
- `text_edit("a","")` == `1.0`（空 gt 分母取 1）

**步骤：**
- [ ] **Step 1:** 写上述失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_text_metric.py -v`，Expected: FAIL（模块不存在）。
- [ ] **Step 3:** 实现 `text_metric.py`。
- [ ] **Step 4:** Run 同上，Expected: 全部 passed。
- [ ] **Step 5:** 提交 `feat(eval): add Text Edit normalized levenshtein metric`。

---

## Task 3: 表格抽取与树构建

**Files:** Create `finix_restore/eval/tables.py`；Test `tests/test_eval_tables.py`

**实现要点：**
- `TableNode` dataclass（字段见契约）。
- HTML 路径：用 `BeautifulSoup(markdown, "lxml")` 找全部 `<table>`，逐 `<tr>` 收 `<td>/<th>` 为子节点；`colspan/rowspan` 解析为 `int`（非法/缺省取 1）；单元格文本 `get_text(" ", strip=True)` 后空白归一。
- Markdown 路径：识别"表头行 + 分隔行（`|:- |` 组成）+ 若干数据行"的连续块，转为 `<table>` 字符串后复用 HTML 解析。

**关键转换规则（易误解，保留小片段）** —— Markdown 分隔行判定与单元格切分：

```python
sep = re.fullmatch(r"\|[:\- |]+\|", line.strip())          # 分隔行
cells = [c.strip() for c in row.strip().strip("|").split("|")]  # 单元格
```

**测试用例（验收）：**
- HTML 表：含 `rowspan="2"` 与 `colspan="2"` 的两行表，断言根 `tag=="table"`、行数、首格 `text/rowspan/colspan`。
- Markdown pipe 表：表头 + 一行数据，断言转为 2 行、首格与末格文本正确。
- 无表文本：`extract_tables(...)` 返回 `[]`。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_tables.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `tables.py`。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): extract HTML and markdown tables into node trees`。

---

## Task 4: Table TEDS 指标

**Files:** Create `finix_restore/eval/table_teds.py`；Test `tests/test_eval_table_teds.py`

**实现要点：**
- 用 `apted.APTED` + 自定义 `Config`：`children(node)` 返回 `node.children`；`rename` 代价按接口契约的「关键公式契约」实现。
- `size(tree)` 递归数节点；单表 TEDS 用归一化公式。
- `table_teds`：双方无表返回 `None`；逐表配对、缺配对计 0、取均值。`has_any_table` 任一侧有表即真。

**测试用例（验收）：**
- 相同表 → `100.0`。
- 仅单元格文本不同 → `0 < score < 100`。
- 双方无表 → `None`。
- `has_any_table`：一侧有表→`True`，双方无表→`False`。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_table_teds.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `table_teds.py`。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): add Table TEDS metric via apted tree edit distance`。

---

## Task 5: Read Order Edit 指标

**Files:** Create `finix_restore/eval/reading_order.py`；Test `tests/test_eval_reading_order.py`

**实现要点：**
- `split_blocks`：`re.split(r"\n\s*\n", text)` 切块，丢空块；每块判 `kind`（`#`→h，`<table`/`|`→t，`^(\d+[.)]|[-*+])\s`→l，否则 p），签名 `"{kind}:{md5(norm)[:12]}"`。
- `read_order_edit`：签名序列做序列级 Levenshtein，除以 `max(1, len(gt_blocks))`。

**测试用例（验收）：**
- `# Title\n\npara\n\n## Sub\n\npara2` → 4 块，签名前缀依次 `h/p/h/p`。
- 相同文本 → `0.0`。
- 块顺序对调 → `> 0.0`。
- gt 为空 → `1.0`（分母取 1）。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_reading_order.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `reading_order.py`。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): add Read Order Edit block-level metric`。

---

## Task 6: 输入读取与对齐（io）

**Files:** Create `finix_restore/eval/io.py`；Test `tests/test_eval_io.py`

**实现要点：**
- `_read_submission_csv`：用 `utf-8-sig` 读取，校验列含 `file_name`/`ground_truth`，否则抛 `ValueError`；返回 `{file_name: ground_truth}`。
- `_load_mapping`：把 `uuid`、`uuid.md`、`afts_id`、`afts_id.{md,png,jpg}` 全部映射到 `{uuid}.md`。
- `load_pairs`：GT 为目录时按映射读取 `{uuid}.md`，目录模式 `missing_pred=[]`；GT 为 CSV 时按 file_name 取，可计算 `missing_pred`。

**测试用例（验收）：**
- 两份 CSV：对齐 2 条，`missing_gt/missing_pred` 为空，文本对应正确。
- 缺项：预测多 1、GT 多 1 → 分别落入 `missing_gt`/`missing_pred`，pairs 只含交集。
- 目录 + mapping：`afts-1.png` 经 `uuid-1` 命中 `uuid-1.md`，pairs 正确、无缺失。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_io.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `io.py`（仅 `_read_submission_csv`、`_load_mapping`、`load_pairs` 三个对象）。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): load and align prediction/GT pairs from csv or mds dir`。

---

## Task 7: Scorer 合成 Overall

**Files:** Create `finix_restore/eval/scorer.py`；Modify `finix_restore/eval/__init__.py`；Test `tests/test_eval_scorer.py`

**实现要点：**
- `score_pair` 调用三项指标；`has_table = (table_teds is not None)`；表格分量 = `teds if has_table else 100.0`；按公式算 `overall`。
- `evaluate` 调 `load_pairs` 后逐条 `score_pair`，聚合均值；`mean_table_teds` 仅对 `has_table` 样本求均值并记 `table_sample_count`；`output` 写 JSON（`ensure_ascii=False, indent=2`）。
- `__init__.py` 导出 `evaluate, score_pair`。

**测试用例（验收）：**
- 无表样本（pred==gt）：`text_edit==0`、`read_order_edit==0`、`table_teds is None`、`has_table False`、`overall==100.0`。
- 含表样本（pred==gt）：`has_table True`、`table_teds==100.0`、`overall==100.0`。
- `evaluate` 两条（1 含表 1 无表，均 pred==gt）：`file_count==2`、`mean_overall==100.0`、`mean_table_teds==100.0`、`table_sample_count==1`，且 JSON 落盘字段一致。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_scorer.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `scorer.py` 并更新 `__init__.py` 导出。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): aggregate three metrics into official Overall score`。

---

## Task 8: CLI 入口

**Files:** Create `finix_restore/eval/cli.py`；Test `tests/test_eval_cli.py`

**实现要点：** `argparse` 解析参数（见契约），调 `evaluate`，打印 `mean_text_edit`/`mean_table_teds`/`mean_read_order_edit`/`Overall` 与缺失计数，返回 0。`__main__` 守卫调用 `main`。

**测试用例（验收）：** 用临时 CSV（pred==gt 1 条）调 `main([...])` 返回 0；JSON `file_count==1`；stdout 含 `"Overall"`。

**步骤：**
- [ ] **Step 1:** 写失败测试。
- [ ] **Step 2:** Run `pytest tests/test_eval_cli.py -v`，Expected: FAIL。
- [ ] **Step 3:** 实现 `cli.py`。
- [ ] **Step 4:** Run 同上，Expected: passed。
- [ ] **Step 5:** 提交 `feat(eval): add scorer CLI entry point`。

---

## Task 9: 全量验证与验收

**Files:** 无新增。

**验收标准（必须全部满足）：**
- `pytest -q` 全绿，含新增 7 个 eval 测试文件，且 `tests/test_local_eval.py` 等既有测试不回归。
- `ruff check finix_restore/eval tests` 无错误。
- 自洽冒烟：构造最小预测 CSV（pred 与 gt 用同一份），CLI 输出 `Overall == 100.00`、JSON 字段完整。
- 差异冒烟（非自洽）：取一份与 GT 有已知差异的预测，确认 `mean_overall < 100`、含表样本 `table_teds` 落在 `(0,100)`、`missing_*` 统计正确 —— 用于验证指标对差异敏感、非恒等返回满分。

**步骤：**
- [ ] **Step 1:** Run `pytest -q`，Expected: 全绿。
- [ ] **Step 2:** Run `ruff check finix_restore/eval tests`，Expected: 无错误（有则修复重跑）。
- [ ] **Step 3:** 自洽冒烟：
  ```bash
  python -m finix_restore.eval.cli --pred /tmp/smoke_pred.csv --gt /tmp/smoke_pred.csv --output outputs/eval/smoke_metrics.json
  ```
  Expected: 打印 `Overall 100.00`；JSON 字段完整。
- [ ] **Step 4:** 差异冒烟：改一份预测使其与 GT 不同，确认上述差异验收标准成立。
- [ ] **Step 5:** 最终提交（lint 修复/产物清理）。注意：`outputs/` 仅放产物、不入库，勿 `git add`。
- [ ] **Step 6:** 发起 PR，描述引用本计划与设计文档，列出新增模块与验收结果。
