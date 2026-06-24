# Table Structure Reading Order Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AFAC Task2 增强表格页结构还原、长条文档阅读顺序恢复和提交前风险门禁，优先解决当前 A 榜 60.7775 分的主要瓶颈。

**Architecture:** 保持现有 `finix_restore` pipeline 主干不大改，在 table 分支新增表格切分计划、表格解析、行级拼接和保守 HTML 修复；在 long 分支新增切线规划和逻辑块辅助排序。最终仍由 `QualityGate` 阻断高风险输出，`SubmissionWriter` 只写通过校验的 CSV。

**Tech Stack:** Python 3.12, dataclasses, BeautifulSoup, Pillow/numpy, pytest, existing `finix_restore.eval` scorer, existing FinixDoc-VL client only.

---

## 0. 范围与强约束

需求来源：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/superpowers/specs/2026-06-24-table-structure-reading-order-optimization-design.md`

本计划必须遵守：

- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data`。
- 不读取、打印、复制或提交 `.env` 中的真实密钥。
- 不调用 FinixDoc-VL 之外的任何大模型、VLM 或 OCR API。
- 不按训练集、A 榜、B 榜文件名写特判逻辑。
- 运行产物只进入 `outputs/`，不要提交。
- 计划文档只放接口契约、关键小片段和关键 diff；大段完整实现进入代码文件和 PR diff。

## 1. 文件结构

新增文件：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`
  - 表格切分计划的数据结构与 `TableStructurePlanner`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`
  - 将 chunk Markdown 解析成表格行、单元格和表格前后文本。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`
  - 按 `row_band`、`col_band` 拼接横向/纵向切开的表格。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/block_segments.py`
  - 长条文档逻辑块切分：标题、段落、列表、表格、目录、页眉页脚等。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cutline_planner.py`
  - 长条文档切线选择辅助函数。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_block_segments.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py`

修改文件：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
  - 给 `Chunk` 增加向后兼容的表格拼接元数据字段。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
  - table 使用 `TableStructurePlanner`；long 使用 `LongCutlinePlanner`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_merger.py`
  - 保持 `repair(markdown)` 公共接口，增强 HTML fragment 修复。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/reading_order.py`
  - 保持 `resolve()` 接口，使用逻辑块元数据保护目录/表格/页眉页脚。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py`
  - 增加块级 overlap 保护，避免误删目录和表格内容。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
  - 暴露 table HTML 状态辅助函数，保留风险指标。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
  - 将 `html_broken`、异常短 table 输出映射为可执行重跑策略。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - table 页进入 parser/assembler 后再做最终 repair。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py`
  - 增加可选 QC summary 风险阻断参数。
- 相关测试：
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_reading_order.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_validate_submission.py`

## 2. 接口契约

### 2.1 `Chunk` 表格元数据

`Chunk` 必须向后兼容，所有新增字段都要有默认值，避免现有测试构造器失效。

关键 diff：

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    file_name: str
    image_path: Path
    bbox: tuple[int, int, int, int]
    row: int
    col: int
    overlap: dict[str, int]
    image_sha1: str
    chunk_pixels: int = 0
    is_last_row: bool = False
    is_last_col: bool = False
    cut_source: str = "unknown"
    risk_flags: tuple[str, ...] = ()
    table_group_id: str | None = None
    row_band: int | None = None
    col_band: int | None = None
    base_bbox: tuple[int, int, int, int] | None = None
    overlap_bbox: tuple[int, int, int, int] | None = None
    requires_row_assembly: bool = False
```

契约：

- `bbox` 仍表示实际发给 FinixDoc-VL 的 crop 区域。
- `base_bbox` 表示未加 overlap 的逻辑行带/列带区域。
- `overlap_bbox` 对 table chunk 等于 `bbox`。
- `row_band`、`col_band` 是从 0 开始的逻辑 band 索引。
- `requires_row_assembly=True` 表示该 chunk 的表格输出不能直接作为最终独立表格。

### 2.2 `TableStructurePlanner`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`

公共接口：

```python
@dataclass(frozen=True)
class TablePlanEntry:
    base_bbox: tuple[int, int, int, int]
    crop_bbox: tuple[int, int, int, int]
    row_band: int
    col_band: int
    rows: int
    cols: int
    cut_source: str
    risk_flags: tuple[str, ...]

@dataclass(frozen=True)
class TablePlan:
    content_box: tuple[int, int, int, int]
    entries: tuple[TablePlanEntry, ...]
    policy: str

class TableStructurePlanner:
    def plan(self, profile: ImageProfile, hints: LayoutHints, config: ChunkConfig) -> TablePlan:
        """Return table-aware chunk plan without writing files."""
```

规则：

- `content_pixels <= table.full_page_max_pixels` 时返回单个 `full_page` entry。
- 需要切分时优先少列、保行带，避免只按面积平方根切成固定网格。
- 未命中空白带或结构线时，entry 标记 `fixed_cut`。
- `cols > 1` 或 `rows > 1` 时，后续 chunk 必须设置 `requires_row_assembly=True`。

### 2.3 `TableChunkParser`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`

公共接口：

```python
@dataclass(frozen=True)
class ParsedTable:
    rows: tuple[tuple[str, ...], ...]
    raw_html: str
    header_key: tuple[str, ...]
    broken: bool

@dataclass(frozen=True)
class ParsedChunkTables:
    chunk_text: ChunkText
    leading_text: str
    tables: tuple[ParsedTable, ...]
    trailing_text: str
    warnings: tuple[str, ...]

class TableChunkParser:
    def parse(self, chunk_text: ChunkText) -> ParsedChunkTables:
        """Parse one chunk response into table rows and surrounding text."""
```

规则：

- 单元格只去除首尾空白，不改写数字、百分号、千分号、中文标点或金融文本。
- 空 `<td></td>` 必须保留为空字符串。
- 无 table 时，`tables=()`，原文保留在 `leading_text`。
- HTML 破损时允许 best-effort 解析，并在 `warnings` 中加入 `html_broken`。

### 2.4 `TableRowAssembler`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`

公共接口：

```python
@dataclass(frozen=True)
class TableAssemblyResult:
    markdown: str
    warnings: tuple[str, ...]
    assembled_tables: int

class TableRowAssembler:
    def assemble(self, ordered_chunks: Sequence[ChunkText]) -> TableAssemblyResult:
        """Assemble table-page chunks into document-level Markdown."""
```

规则：

- 先按 `table_group_id` 分组，再按 `row_band`、`col_band` 排序。
- 同一 `row_band` 内，仅在行数或行 key 可对齐时做横向拼接。
- 相邻 `row_band` 纵向拼接时删除重复表头。
- 对齐不确定时保留原 chunk 顺序并输出 `row_alignment_uncertain` warning，不猜测合并。

### 2.5 Pipeline 路由

关键 diff 形态：

```python
if profile.doc_type == "table_page":
    assembled = self.table_assembler.assemble(ordered)
    repaired = self.table_merger.repair(assembled.markdown)
else:
    merged = self.dedup.merge(ordered)
    repaired = self.table_merger.repair(merged.markdown)
```

契约：

- normal/long 页默认保持现有 merge 路径。
- table 页在 normalized + reading order 之后，先 assembly，再最终 HTML repair。
- `QualityGate.check_file()` 仍是写 CSV 前的最终质量判断。

## 3. Task 1: 增加 Chunk 表格元数据

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chunkers.py` 中断言 table chunk 和 manifest 都包含 `row_band`、`col_band`、`base_bbox`、`overlap_bbox`、`requires_row_assembly`。

关键断言：

```python
assert chunks[0].row_band == 0
assert chunks[0].col_band == 0
assert chunks[0].base_bbox is not None
assert chunks[0].overlap_bbox == chunks[0].bbox
assert "requires_row_assembly" in manifest["chunks"][0]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_chunkers.py::test_table_grid_chunks_respect_bounds_and_max_pixels -q
```

Expected: 失败，原因是 `Chunk` 或 manifest 中缺少新增字段。

- [ ] **Step 3: 修改 `Chunk`**

按 2.1 的关键 diff 增加默认字段，保持现有构造器可用。

- [ ] **Step 4: 在 `TableGridChunker._materialize()` 填充元数据**

设置：

- `table_group_id=Path(profile.file_name).stem`
- `row_band=row`
- `col_band=col`
- `base_bbox` 来自未加 overlap 的 entry
- `overlap_bbox=bbox`
- `requires_row_assembly=(rows > 1 or cols > 1)`

不得改变 `Chunk.bbox` 的语义。

- [ ] **Step 5: 运行 chunker 测试**

Run:

```bash
pytest tests/test_chunkers.py -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add finix_restore/models.py finix_restore/chunkers.py tests/test_chunkers.py
git commit -m "feat: add table chunk assembly metadata"
```

## 4. Task 2: 增加 TableStructurePlanner

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写 planner 契约测试**

覆盖：

- 小表格命中 `full_page`
- 大表格拆成多个 entry 且不超过 `safe_max_pixels`
- blank-band hints 使至少一个 entry 的 `cut_source="blank_band"`

关键断言：

```python
plan = TableStructurePlanner().plan(profile, hints, cfg)
assert plan.policy == "table_structure_v1"
assert all(entry.crop_bbox[0] <= entry.base_bbox[0] for entry in plan.entries)
assert any(entry.cut_source == "blank_band" for entry in plan.entries)
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_table_structure.py -q
```

Expected: 失败，原因是 `finix_restore.table_structure` 尚不存在。

- [ ] **Step 3: 实现 dataclasses 与 `plan()`**

复用 `TableGridChunker._estimate_grid_shape`、`_adjust_cuts`、`_enforce_pixel_budget` 的思路，但不要复制普通页无关逻辑。

- [ ] **Step 4: 将 `TableGridChunker.chunk()` 接入 planner**

`TableGridChunker.chunk()` 生成 `TablePlan`，再把 `TablePlanEntry` 转成 `_materialize()` 的 entry。

关键 entry 形态：

```python
entries.append({
    "bbox": entry.crop_bbox,
    "base_bbox": entry.base_bbox,
    "row": entry.row_band,
    "col": entry.col_band,
    "rows": entry.rows,
    "cols": entry.cols,
    "cut_source": entry.cut_source,
})
```

- [ ] **Step 5: 运行相关测试**

Run:

```bash
pytest tests/test_table_structure.py tests/test_chunkers.py -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add finix_restore/table_structure.py finix_restore/chunkers.py tests/test_table_structure.py tests/test_chunkers.py
git commit -m "feat: plan table-aware chunk geometry"
```

## 5. Task 3: 增加 TableChunkParser

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py`

- [ ] **Step 1: 写 parser 测试**

覆盖：

- 普通 `td` 表格
- `th` 表头表格
- 空 `<td></td>` 保留为空字符串
- 破损 table 返回 warning 但尽量解析 rows
- 非 table 文本保留在 `leading_text`

关键断言：

```python
parsed = TableChunkParser().parse(chunk_text)
assert parsed.tables[0].rows == (("项目", "金额"), ("A", "1"))
assert parsed.tables[0].header_key == ("项目", "金额")
assert parsed.tables[0].broken is False
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_table_parser.py -q
```

Expected: import failure。

- [ ] **Step 3: 实现 parser**

使用 BeautifulSoup 和保守 regex 定位 table fragment。只剥离单元格首尾空白，不做金融文本纠错。

强约束：

```python
cell.get_text(strip=True)
```

只能用于剥离首尾空白，不得改写数字、符号或中文内容。

- [ ] **Step 4: 运行 parser 测试**

Run:

```bash
pytest tests/test_table_parser.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add finix_restore/table_parser.py tests/test_table_parser.py
git commit -m "feat: parse table chunks into rows"
```

## 6. Task 4: 增加 TableRowAssembler

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py`

- [ ] **Step 1: 写横向拼接测试**

构造两个相同 `row_band`、相邻 `col_band` 的 `ChunkText`：

```text
left:  <tr><td>终身</td><td>1</td></tr>
right: <tr><td>男</td><td>2176</td></tr>
```

期望拼接为：

```html
<tr><td>终身</td><td>1</td><td>男</td><td>2176</td></tr>
```

- [ ] **Step 2: 写纵向拼接测试**

构造两个 row band：都有重复表头，但 body 行不同。期望输出只保留一次表头，并保留两个 body 行。

- [ ] **Step 3: 写不确定对齐测试**

构造同一 row band 但左右表格行数不同的输入。期望保留原局部表，并输出 `row_alignment_uncertain` warning。

- [ ] **Step 4: 运行失败测试**

Run:

```bash
pytest tests/test_table_assembler.py -q
```

Expected: import failure。

- [ ] **Step 5: 实现 assembler**

实现 2.4 接口。第一版只做保守规则：

- 行数完全一致才横向逐行拼接。
- 首行完全重复才删除重复表头。
- 不确定对齐时保留原顺序，不做猜测。

- [ ] **Step 6: 运行 assembler 测试**

Run:

```bash
pytest tests/test_table_assembler.py -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add finix_restore/table_assembler.py tests/test_table_assembler.py
git commit -m "feat: assemble split table chunks"
```

## 7. Task 5: 增强 TableMerger HTML 修复

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_merger.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py`

- [ ] **Step 1: 增加 no-wrapper 测试**

断言破损 table fragment 修复后不会引入 `<html>` 或 `<body>` 外壳。

关键断言：

```python
assert "<html" not in repaired.lower()
assert "<body" not in repaired.lower()
```

- [ ] **Step 2: 增加多 table 缺失闭合标签测试**

构造多个 `<table>` open、缺少 close 的片段。断言 `repaired_tags > 0`，且经 `QualityGate` 检查后不再触发 `html_broken`。

- [ ] **Step 3: 运行失败测试**

Run:

```bash
pytest tests/test_table_merger.py -q
```

Expected: 新增 no-wrapper 或多 table 修复断言失败。

- [ ] **Step 4: 实现保守 cleanup**

保持 `TableMerger.repair(markdown: str) -> TableRepairResult` 不变。BeautifulSoup 产生 wrapper 时只输出 body 的 children。

关键片段：

```python
body = soup.body
markdown = "".join(str(child) for child in body.children) if body else soup.decode(formatter="minimal")
```

- [ ] **Step 5: 运行相关测试**

Run:

```bash
pytest tests/test_table_merger.py tests/test_quality_gate.py -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add finix_restore/table_merger.py tests/test_table_merger.py
git commit -m "fix: repair table html fragments conservatively"
```

## 8. Task 6: 接入 Pipeline table assembly

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py`

- [ ] **Step 1: 写 mocked Finix client pipeline 测试**

构造 table 图片 fixture，monkeypatch `FinixApiClient` 返回两个横向切开的表格 chunk。断言输出 CSV 中出现拼接后的单行，而不是两个独立表格片段。

关键断言：

```python
assert "<td>终身</td><td>1</td><td>男</td><td>2176</td>" in df.loc[0, "ground_truth"]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_pipeline_table_assembly.py -q
```

Expected: 输出尚未拼接，测试失败。

- [ ] **Step 3: 在 `Pipeline.__init__` 注入 assembler**

```python
self.table_assembler = TableRowAssembler()
```

- [ ] **Step 4: 在 `_process_image_once()` 接入 table 分支**

按 2.5 的路由契约接入。normal/long 分支保持原路径。

- [ ] **Step 5: 记录 assembler warnings**

将 assembler warnings 放入 QC extra metrics 或日志。此任务只因最终 HTML 破损而阻断，不因普通 warning 直接阻断。

- [ ] **Step 6: 运行 pipeline 测试**

Run:

```bash
pytest tests/test_pipeline_table_assembly.py tests/test_pipeline_quality_blocking.py -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add finix_restore/pipeline.py tests/test_pipeline_table_assembly.py
git commit -m "feat: assemble table chunks in pipeline"
```

## 9. Task 7: 增加 LongCutlinePlanner

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cutline_planner.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 增加切线选择测试**

覆盖：

- 目标附近有 blank band 时选择 blank band 中心。
- 无 blank band 时回退 dynamic window 并标记 `fixed_cut`。
- 切线不后退、不生成 0 高度 chunk。

关键行为：

```python
cut = LongCutlinePlanner().choose_cut(target_y=3200, y0=0, cy1=8000, bands=[(3150, 3230)], search_px=360)
assert cut.y1 == 3190
assert cut.source == "blank_band"
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_chunkers.py::test_long_cut_adjusts_to_horizontal_blank_band -q
```

Expected: 新增 planner 断言在 module 存在前失败。

- [ ] **Step 3: 实现 `LongCutlinePlanner`**

把现有 `LongStripChunker` 中的切线选择逻辑抽到独立 helper。默认保持 `nearest_band_center` 语义。

- [ ] **Step 4: 将 `LongStripChunker` 接入 planner**

不得改变 chunk 文件名、cache id、覆盖全图的保证。

- [ ] **Step 5: 运行 chunker 测试**

Run:

```bash
pytest tests/test_chunkers.py -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add finix_restore/cutline_planner.py finix_restore/chunkers.py tests/test_chunkers.py
git commit -m "refactor: isolate long cutline planning"
```

## 10. Task 8: 增加 BlockSegmenter 与块级排序钩子

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/block_segments.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/reading_order.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_block_segments.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_reading_order.py`

- [ ] **Step 1: 写 block segmentation 测试**

覆盖 title、paragraph、list_item、table、toc、header_footer candidate。

关键契约：

```python
segments = BlockSegmenter().segment("# 1 总则\n\n正文")
assert [s.block_type for s in segments] == ["title", "paragraph"]
```

- [ ] **Step 2: 写 reading order 回归测试**

构造 TOC chunk 与正文标题文本相似的场景。期望 TOC 不导致正文标题被删除。

- [ ] **Step 3: 运行失败测试**

Run:

```bash
pytest tests/test_block_segments.py tests/test_reading_order.py -q
```

Expected: import failure 或块级行为缺失。

- [ ] **Step 4: 实现 `BlockSegmenter`**

只使用 Markdown/HTML 边界规则，不引入 NLP 或外部模型。

类型契约：

```python
BlockType = Literal["title", "paragraph", "list_item", "table", "toc", "header_footer", "footnote"]
```

- [ ] **Step 5: 在 reading order 与 dedup 中使用块级提示**

保持 `ReadingOrderResolver.resolve()` 签名不变。块级提示只用于保护 TOC/table/header-footer，不在这里改写表格内部。

- [ ] **Step 6: 运行相关测试**

Run:

```bash
pytest tests/test_block_segments.py tests/test_reading_order.py tests/test_dedup.py -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add finix_restore/block_segments.py finix_restore/reading_order.py finix_restore/dedup.py tests/test_block_segments.py tests/test_reading_order.py
git commit -m "feat: add block-aware long ordering helpers"
```

## 11. Task 9: 增强 QualityGate 与 RetryPlanner

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 增加 table HTML status helper 测试**

期望契约：

```python
status = gate.table_html_status("<table><tr><td>A</td></tr></table>")
assert status["html_broken"] == 0
```

破损表格：

```python
status = gate.table_html_status("<table><tr><td>A")
assert status["html_broken"] > 0
```

- [ ] **Step 2: 增加 `html_broken` retry planner 测试**

期望：

- 未超过重跑次数时允许 rerun。
- concurrency 强制为 1。
- reasons 包含 `html_broken`。

- [ ] **Step 3: 运行失败测试**

Run:

```bash
pytest tests/test_quality_gate.py tests/test_pipeline_quality_blocking.py -q
```

Expected: helper 缺失或 planner 行为不匹配。

- [ ] **Step 4: 实现 helper 与 retry mapping**

保留 `_html_is_broken` 私有逻辑；新增公开 helper 供审计脚本和测试使用。

- [ ] **Step 5: 增加破损非空 merged 阻断回归测试**

覆盖一个非空但 table HTML 破损的输出。期望 pipeline 失败且不写 output CSV。

- [ ] **Step 6: 运行相关测试**

Run:

```bash
pytest tests/test_quality_gate.py tests/test_pipeline_quality_blocking.py -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add finix_restore/quality_gate.py finix_restore/retry_planner.py tests/test_quality_gate.py tests/test_pipeline_quality_blocking.py
git commit -m "fix: gate unresolved table html risks"
```

## 12. Task 10: 增加提交前风险校验

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_validate_submission.py`

- [ ] **Step 1: 增加 QC summary 风险阻断 CLI 测试**

构造临时 `summary.json`，内容包含 `risk_counts={"html_broken": 1}`。使用风险阻断参数时，期望输出 `passed=false`。

CLI 契约：

```bash
python scripts/chunk_eval/validate_submission.py \
  --csv submission.csv \
  --expected-dir images \
  --qc-summary qc/summary.json \
  --fail-on-risk html_broken
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest tests/test_chunk_eval_validate_submission.py -q
```

Expected: 新 CLI 参数未识别。

- [ ] **Step 3: 实现 `--qc-summary` 和可重复 `--fail-on-risk` 参数**

未传 QC 参数时，保持当前 validator 行为。

输出 JSON 必须包含：

```json
{
  "blocked_risks": ["html_broken"],
  "risk_counts": {"html_broken": 1}
}
```

- [ ] **Step 4: 运行 validator 测试**

Run:

```bash
pytest tests/test_chunk_eval_validate_submission.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add scripts/chunk_eval/validate_submission.py tests/test_chunk_eval_validate_submission.py
git commit -m "feat: block submissions on qc risks"
```

## 13. Task 11: 记录评估 smoke 命令

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`

- [ ] **Step 1: 记录 table smoke 命令**

在 `docs/experiments.md` 加一段 5 文件 table smoke 命令。命令必须使用 `--limit` 或样本目录，不允许算法里写文件名特判。

- [ ] **Step 2: 记录 long smoke 命令**

添加对应 long smoke 命令和 scorer 命令。

- [ ] **Step 3: 记录风险门禁校验命令**

写入以下命令形态：

```bash
python scripts/chunk_eval/validate_submission.py \
  --csv outputs/chunk_eval/table_structure_smoke/submission.csv \
  --expected-dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --qc-summary outputs/chunk_eval/table_structure_smoke/run/qc/summary.json \
  --fail-on-risk html_broken
```

- [ ] **Step 4: 运行 docs diff check**

Run:

```bash
git diff --check -- docs/experiments.md
```

Expected: 无输出且 exit code 为 0。

- [ ] **Step 5: 提交**

```bash
git add docs/experiments.md
git commit -m "docs: add structure optimization smoke commands"
```

## 14. 最终验证与验收

所有任务完成后运行：

```bash
pytest -q
```

验收：

- 全部单元测试通过。

具备 API 凭据和额度时运行 table smoke：

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --output_csv outputs/chunk_eval/table_structure_smoke/submission.csv \
  --work_dir outputs/chunk_eval/table_structure_smoke/run \
  --config scripts/chunk_eval/configs/balanced_6m.yaml \
  --limit 5 \
  --image_concurrency 1
```

评分：

```bash
python -m finix_restore.eval.cli \
  --pred outputs/chunk_eval/table_structure_smoke/submission.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --output outputs/chunk_eval/table_structure_smoke/metrics.json
```

table smoke 验收：

- `outputs/chunk_eval/table_structure_smoke/run/qc/summary.json` 中 `risk_counts.html_broken` 不存在或为 0。
- Table TEDS 高于当前训练 table 基线 13.86。
- CSV 可读、列名正确、行数正确、无重复文件名、无空输出。

具备 API 凭据和额度时运行 long smoke：

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --output_csv outputs/chunk_eval/long_order_smoke/submission.csv \
  --work_dir outputs/chunk_eval/long_order_smoke/run \
  --config scripts/chunk_eval/configs/balanced_6m.yaml \
  --limit 5 \
  --image_concurrency 1
```

long smoke 验收：

- Read Order Edit 低于当前训练 long 全量基线 0.7128。
- 剩余高风险文件必须在 QC summary 中列出明确风险名。

## 15. 推荐实施顺序

1. Task 1：元数据基础。
2. Task 2：表格切分计划。
3. Task 3：表格解析。
4. Task 4：表格拼接。
5. Task 5：HTML 修复。
6. Task 6：pipeline 集成。
7. Task 9：质量门与重跑。
8. Task 10：提交前风险校验。
9. Task 7 和 Task 8：long 切线与块级顺序。
10. Task 11：实验文档。

原因：

- table 是当前最大分数瓶颈，应先落地。
- 质量门要紧跟 table 集成，防止破损 assembled output 静默进入提交。
- long 阅读顺序重要，但当前没有 table 页那么灾难性。

## 16. Review Checklist

实现完成后检查：

- [ ] 没有新增外部模型/API 依赖。
- [ ] 没有修改 `data/`。
- [ ] 没有针对 train/A/B 文件名的特判。
- [ ] Table parser 保留空单元格和金融数字文本。
- [ ] Table assembler 对不确定行对齐输出 warning，不猜测合并。
- [ ] `TableMerger.repair()` 公共签名不变。
- [ ] `Pipeline.run()` 在 `QualityGate` 失败时仍不写 CSV。
- [ ] Submission validator 可基于 QC summary 阻断 `html_broken`。
- [ ] `pytest -q` 通过。
- [ ] 新的 A/B 提交前，smoke 指标和风险清单已写入 `outputs/` 并审阅。
