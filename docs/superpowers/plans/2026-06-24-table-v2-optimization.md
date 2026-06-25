# Table V2 Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AFAC2026 Task2 训练集 table 类型离线 Overall 从当前约 0.89 提升到至少 60+，并让 A 榜 table 风险从“高频破损/重复”收敛到可提交审计状态。

**Architecture:** 在现有 `finix_restore` pipeline 上新增 table v2 路径：先用 table 专属图像策略生成全页参考和尽量全宽的行带切片，再用保留 span 的表格解析器和 row-level assembler 重建视觉表，最后由 table-aware quality gate 驱动重跑与阻断。long/normal 路径保持现状，table v2 通过配置开关启用，避免影响已有 baseline。

**Tech Stack:** Python 3.12, dataclasses, Pillow, numpy, BeautifulSoup/lxml, rapidfuzz, pandas, pytest, existing `finix_restore.eval` scorer, FinixDoc-VL API only.

---

## 0. 背景、范围与硬约束

### 0.1 当前证据

当前 table 全量训练集结果：

- 指标文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/full_train_balanced_6m_20260624/table/metrics.json`
- `mean_overall = 0.8901`
- `mean_text_edit = 0.6675`
- `mean_table_teds = 13.6785`
- `mean_read_order_edit = 1.4426`

当前 table 质量风险：

- 校验文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/full_train_balanced_6m_20260624/table/validate_report.json`
- `html_broken = 12`
- `high_duplication = 11`
- `api_failure_ratio_high = 5`
- `too_short = 1`

A 榜 table 风险：

- 风险文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/a_eval/balanced_6m_full/risk_summary.md`
- 50 个 table 样本中 20 个被标红。
- `html_broken = 18`
- `high_duplication = 3`

### 0.2 本计划只解决 table v2

本计划不继续扩展 long 侧阅读顺序，不重构通用 pipeline，不接入新模型。目标是让 table 路径先形成可评测、可复现、可迁移的结构恢复能力。

### 0.3 强约束

- 不修改、重命名或覆盖 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data` 下原始数据。
- 不读取、打印、复制或提交 `.env` 中真实密钥。
- 不调用 FinixDoc-VL 以外的任何外部大模型、VLM 或 OCR API。
- 不引入 GPU 依赖，不引入超过赛题限制的本地模型。
- 不按训练集、A 榜、B 榜文件名写特判逻辑。
- 运行产物只写入 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs`。
- 计划文档只保留接口契约、关键小 diff 和验收命令；大段完整实现进入代码仓库和 PR。

### 0.4 本次审核修订点

本计划经审核后修正以下可执行性问题：

- 补齐 `TablePlanEntry` 与 `Chunk` 之间的 v2 字段传递契约，避免 planner 产生的锚定列、缩放比例无法进入 manifest。
- 明确 `QualityGate` 所需的 table v2 extra metrics，避免 QC 规则依赖 pipeline 无法提供的信息。
- 增加独立的 `TableMerger` 任务；原计划列出了修改文件，但没有对应测试和实施步骤。
- 将 smoke 验收从简单 `--limit 20` 改为基于训练集 profile 的像素分位样本，避免只评估文件名排序前 20 张。
- 明确 QC 阻断时不能继续把缺失的 `submission.csv` 当作评分输入；兜底 CSV 只能用于诊断。

## 1. 目标指标与验收口径

### 1.1 训练集 table 必达指标

以 100 张训练 table 全量为准：

| 指标 | 必达线 | 推荐线 |
| --- | ---: | ---: |
| Overall | >= 60.00 | >= 69.00 |
| Text Edit | <= 0.20 | <= 0.18 |
| Table TEDS | >= 40.00 | >= 55.00 |
| Read Order Edit | <= 0.40 | <= 0.30 |
| `html_broken` | 0 | 0 |
| `high_duplication` | <= 2 | 0 |
| `api_failure_ratio_high` | 0 | 0 |

最低 60 分组合为：

```text
((1 - 0.20) * 100 + 40 + (1 - 0.40) * 100) / 3 = 60
```

### 1.2 A 榜 table 提交前审计

A 榜无 GT，本地不计算 table 精确分。提交前必须满足：

- `submission.csv` 可读。
- 列名严格为 `file_name,ground_truth`。
- 行数为 100。
- 无重复文件名。
- 无空输出。
- table 页 `html_broken = 0`。
- table 页 `api_failure_ratio_high = 0`。
- table 页 `table_count_explosion <= 2`，且每个样本有人工可解释原因。

## 2. 文件结构

### 2.1 新增文件

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_image_policy.py`
  - table v2 图像策略：安全内容框、降采样比例、全页参考、全宽行带优先策略。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py`
  - 训练集 table 诊断汇总：指标、长度比、表格数差异、chunk shape、QC 风险。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_v2.yaml`
  - table v2 默认配置，保守并发，启用全页参考和全宽行带。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py`
  - table v2 图像策略单测。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_table_failures.py`
  - table 诊断脚本单测。

### 2.2 修改文件

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
  - 扩展 `TableChunkConfig`，增加 table v2 配置字段。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
  - 扩展 `Chunk` 元数据，记录原图 bbox、发送给 API 的图像尺寸和缩放比例。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
  - table 页根据配置选择 `table_grid_v2` 或 `table_v2_rowband`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`
  - 将固定二维网格升级为行带优先计划。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`
  - 保留 `rowspan/colspan/th`，输出 `ParsedCell`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`
  - 支持带文本块的纵向合并、overlap 行去重、横向锚定列对齐。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_merger.py`
  - 保守 HTML 合法化，避免引入 `<html><body>` 外壳。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
  - 增加 `table_count_explosion`、`table_assembly_uncertain` 风险。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
  - 将 table v2 风险映射为低并发、强制 API、改用行带或参考图重跑。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - table v2 产物指标写入 `extra_metrics`，QC 失败时稳定落盘 summary。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py`

## 3. 接口契约

### 3.1 `TableChunkConfig`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`

新增字段必须带默认值，保证旧配置可继续运行。

关键 diff：

```python
@dataclass(frozen=True)
class TableChunkConfig:
    policy_version: str = "grid_v2"
    full_page_reference_max_pixels: int = 14_000_000
    row_band_target_pixels: int = 8_000_000
    row_band_safe_pixels: int = 12_000_000
    min_crop_coverage: float = 0.55
    preserve_full_width: bool = True
    allow_horizontal_split: bool = True
    anchor_left_px: int = 640
```

契约：

- `policy_version="grid_v2"` 保持旧行为。
- `policy_version="rowband_v2"` 启用 table v2。
- `full_page_reference_max_pixels` 只控制本地降采样参考图，不改变原图。
- `preserve_full_width=True` 时 planner 必须优先缩放后全宽行带，而不是横向切列。
- `allow_horizontal_split=False` 时，超过预算的行带必须继续纵向切或降采样，不得生成多列切片。

### 3.2 `TableImagePolicy`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_image_policy.py`

公共接口：

```python
@dataclass(frozen=True)
class TableImageVariant:
    kind: str
    source_bbox: tuple[int, int, int, int]
    sent_width: int
    sent_height: int
    scale: float
    risk_flags: tuple[str, ...]

@dataclass(frozen=True)
class TableImagePlan:
    content_box: tuple[int, int, int, int]
    reference: TableImageVariant | None
    crop_mode: str
    warnings: tuple[str, ...]

class TableImagePolicy:
    def plan(self, profile: ImageProfile, hints: LayoutHints, config: ChunkConfig) -> TableImagePlan:
        raise NotImplementedError
```

契约：

- `source_bbox` 使用原图坐标。
- `sent_width/sent_height` 是实际发给 FinixDoc-VL 的图片尺寸。
- `scale <= 1.0`，表示本地等比降采样比例。
- 当 `crop_box` 覆盖率低于 `min_crop_coverage` 时，`crop_mode="full_image_fallback"`。
- `reference.kind="full_page_reference"` 时，该图只作为全局结构参考，不能替代高分辨率行带结果。

### 3.3 `Chunk` table v2 元数据

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`

关键 diff：

```python
sent_width: int | None = None
sent_height: int | None = None
render_scale: float = 1.0
variant_kind: str | None = None
anchor_bbox: tuple[int, int, int, int] | None = None
```

契约：

- `bbox` 继续表示该 chunk 在原图坐标中的语义区域。
- `image_path` 指向实际发送给 FinixDoc-VL 的本地图片，可为原尺寸 crop，也可为降采样 crop。
- `sent_width/sent_height` 必须与 `image_path` 实际尺寸一致。
- `render_scale` 仅用于审计和复盘，不用于改写 Markdown 文本。

### 3.4 `TableStructurePlanner` row-band v2

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`

`TablePlanEntry` 需要补齐 v2 字段，供 `TableGridChunker._materialize()` 写入 `Chunk` 和 manifest。

关键 diff：

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
    render_scale: float = 1.0
    variant_kind: str = "table_crop"
    sent_width: int | None = None
    sent_height: int | None = None
    anchor_bbox: tuple[int, int, int, int] | None = None
```

`TableStructurePlanner` 公共接口保持：

```python
class TableStructurePlanner:
    def plan(self, profile: ImageProfile, hints: LayoutHints, config: ChunkConfig) -> TablePlan:
        raise NotImplementedError
```

契约：

- `config.table.policy_version="grid_v2"` 时保持旧 `table_grid_v2` 结果。
- `config.table.policy_version="rowband_v2"` 时优先生成 `rows > 1, cols = 1`。
- 当 `TableImagePolicy.plan().reference` 非空时，planner 必须生成一个 `variant_kind="full_page_reference"` 的 reference entry，`row_band=-1`、`col_band=0`，并排在所有 row-band entries 之前。
- 仅当全宽行带在降采样后仍超过 `row_band_safe_pixels` 且 `allow_horizontal_split=True` 时，允许 `cols > 1`。
- `cut_source` 可取：`full_page`、`full_page_reference`、`row_band`、`blank_band`、`line_band`、`horizontal_fallback`。
- 任何 `cols > 1` entry 必须设置 `anchor_bbox`，且 `risk_flags` 包含 `horizontal_split`.
- 任何 `render_scale < 1.0` entry 必须设置 `sent_width/sent_height`，并在 manifest 中可审计。

### 3.5 `ParsedCell` 与 `ParsedTable`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`

关键接口：

```python
@dataclass(frozen=True)
class ParsedCell:
    text: str
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False

@dataclass(frozen=True)
class ParsedTable:
    rows: tuple[tuple[ParsedCell, ...], ...]
    raw_html: str
    header_key: tuple[str, ...]
    broken: bool
```

契约：

- 单元格文本只做首尾空白清理。
- 空 `<td></td>` 保留为 `ParsedCell(text="")`。
- `th` 转为 `ParsedCell(is_header=True)`。
- `rowspan/colspan` 非法值按 1 处理，并在 warnings 中记录 `invalid_span`。
- 不改写金额、百分号、千分号、年龄、年度、条款编号。

### 3.6 `TableRowAssembler` v2

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`

公共接口保持：

```python
class TableRowAssembler:
    def assemble(self, ordered_chunks: Sequence[ChunkText]) -> TableAssemblyResult:
        raise NotImplementedError
```

契约：

- `variant_kind="full_page_reference"` 的 chunk 只提供表题、说明、表数量和全局顺序提示，不直接覆盖 row-band 表格内容。
- 同一 `row_band` 内，`cols == 1` 时直接解析为该行带表格块。
- 同一 `row_band` 内，`cols > 1` 时必须使用锚定列签名对齐。
- 相邻 `row_band` 纵向合并时删除重复表头和 overlap 重复行。
- 对齐置信不足时输出 `table_assembly_uncertain`，并保留原 chunk 顺序。
- 渲染 HTML 时必须保留 `rowspan/colspan` 和 header 标记。

### 3.7 `QualityGate` table v2 风险

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`

新增风险：

- `table_count_explosion`
- `table_assembly_uncertain`
- `table_reference_missing`
- `horizontal_split_unmerged`

契约：

- `table_count_explosion` 判定：`doc_type == "table_page"` 且 `table_count > max(3, chunk_count // 2)`。
- `table_assembly_uncertain` 来自 assembler warning。
- `table_reference_missing` 判定：`table_policy == "table_rowband_v2"` 且 `table_reference_chunks == 0`。
- `horizontal_split_unmerged` 来自存在 `horizontal_split` chunk 且最终 table 数未下降。
- 这些风险写入文件级 QC，不直接写入 Markdown。

`QualityGate.check_file()` 依赖 pipeline 传入以下 `extra_metrics`：

```python
{
    "table_count": int,
    "table_count_before_assembly": int,
    "horizontal_split_chunks": int,
    "table_reference_chunks": int,
    "table_policy": str,
    "table_assembled_tables": int,
    "table_assembly_warnings": str,
}
```

缺少这些指标时，QC 不得猜测 `horizontal_split_unmerged`，只能跳过该风险并保留已有 HTML、重复率和 API 失败率检查。

## 4. 开发任务

### Task 1: 增加 table v2 配置与诊断脚本

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_v2.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_table_failures.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py`

- [ ] **Step 1: 写配置解析失败测试**

测试点：

- `TableChunkConfig.policy_version == "rowband_v2"` 可从 YAML mapping 读入。
- 未提供新字段时保持旧默认值。
- `ChunkConfig.to_dict()` 包含新增 table 字段。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py -q
```

Expected: 新断言在实现前失败。

- [ ] **Step 2: 扩展 `TableChunkConfig`**

只增加 3.1 中列出的字段和默认值，不改变 `LongChunkConfig`、`NormalChunkConfig`。

- [ ] **Step 3: 新增 `configs/table_v2.yaml`**

关键配置必须包含：

```yaml
chunk:
  table:
    policy_version: rowband_v2
    full_page_reference_max_pixels: 14000000
    row_band_target_pixels: 8000000
    row_band_safe_pixels: 12000000
    preserve_full_width: true
    allow_horizontal_split: true
api:
  timeout_seconds: 420
  concurrency: 10
  per_user_concurrency: 2
runtime:
  image_concurrency: 4
```

- [ ] **Step 4: 写 table 诊断脚本测试**

构造一个小型 metrics JSON、manifest JSON、QC summary 和预测/GT CSV，断言输出 Markdown 包含：

- 指标汇总。
- 长度比分位数。
- `pred_tables > gt_tables` 计数。
- chunk shape 分布。
- 风险计数。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_table_failures.py -q
```

Expected: 脚本未创建前失败。

- [ ] **Step 5: 实现 `summarize_table_failures.py`**

接口：

```bash
python /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py \
  --metrics outputs/chunk_eval/full_train_balanced_6m_20260624/table/metrics.json \
  --pred outputs/chunk_eval/full_train_balanced_6m_20260624/table/submission_from_merged.csv \
  --gt-dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --run-dir outputs/chunk_eval/full_train_balanced_6m_20260624/table/run \
  --out outputs/chunk_eval/full_train_balanced_6m_20260624/table/table_failure_summary.md
```

脚本必须调用 `csv.field_size_limit`，避免超长 Markdown 字段读取失败。

- [ ] **Step 6: 运行任务测试**

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_table_failures.py \
  -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_v2.yaml \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_table_failures.py
git commit -m "feat: add table v2 config and diagnostics"
```

### Task 2: 增加 table 图像策略与安全 crop

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_image_policy.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py`

- [ ] **Step 1: 写安全 crop 测试**

覆盖：

- crop 覆盖率低于 `min_crop_coverage` 时使用全图。
- crop 覆盖率足够时扩展 margin 后使用 crop。
- 全页参考按 `full_page_reference_max_pixels` 计算 `scale`。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py -q
```

Expected: `ModuleNotFoundError: finix_restore.table_image_policy`。

- [ ] **Step 2: 实现 `TableImagePolicy` 接口**

按 3.2 的 dataclass 和 `plan()` 契约实现。不得读取图片像素内容，只基于 `ImageProfile`、`LayoutHints`、`ChunkConfig` 做决策。

- [ ] **Step 3: 运行任务测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_image_policy.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py
git commit -m "feat: add table image policy"
```

### Task 3: 扩展 Chunk 元数据并支持降采样 crop 落盘

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写 manifest 元数据测试**

断言 table v2 chunk manifest 包含：

- `sent_width`
- `sent_height`
- `render_scale`
- `variant_kind`
- `anchor_bbox`

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_table_grid_chunks_respect_bounds_and_max_pixels -q
```

Expected: 新字段缺失导致失败。

- [ ] **Step 2: 扩展 `Chunk`**

按 3.3 增加默认字段，保持所有现有 `Chunk(...)` 构造调用不需要修改也能通过。

- [ ] **Step 3: 增加 `_save_crop` 缩放参数**

关键签名：

```python
def _save_crop(source: Path, bbox: tuple[int, int, int, int], out_path: Path, scale: float = 1.0) -> tuple[int, int]:
    raise NotImplementedError
```

契约：

- 返回实际保存图片尺寸。
- `scale == 1.0` 时保持旧行为。
- `scale < 1.0` 时只缩小，不放大。

- [ ] **Step 4: 运行 chunker 测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: record table chunk render metadata"
```

### Task 4: 实现 row-band-first TableStructurePlanner

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写 row-band planner 失败测试**

新增测试断言：

- `policy_version="rowband_v2"` 时，宽高为 `12000x9000` 的 table 默认生成 `cols == 1` 的多个 row bands。
- 启用 `full_page_reference_max_pixels` 时，plan 包含 `variant_kind="full_page_reference"` 且 `row_band == -1` 的 reference entry。
- 生成的每个 entry 在降采样后不超过 `row_band_safe_pixels`。
- `allow_horizontal_split=False` 时没有 `horizontal_split` 风险。
- `policy_version="grid_v2"` 时旧测试仍得到原 `table_grid_v2` 行为，确保 table v2 可关闭。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py -q
```

Expected: row-band 新断言失败。

- [ ] **Step 2: 实现 row-band v2 分支**

实现规则：

- 先调用 `TableImagePolicy.plan()` 获取 `content_box` 和参考图策略。
- 如果 reference 非空，先生成 reference entry，供 API 获取全局表题、说明和粗结构。
- 根据 `row_band_target_pixels` 估算行带高度。
- 优先使用 `hints.horizontal_blank_bands` 附近切线。
- 找不到空白带时使用固定行带，但 `cut_source` 标记为 `row_band` 或 `horizontal_fallback`。
- 只有在全宽行带缩放后仍超预算时，才生成列切分。
- 每个 entry 必须填充 `render_scale`、`variant_kind`、`sent_width`、`sent_height`；横向列切 entry 还必须填充 `anchor_bbox`。

- [ ] **Step 3: table chunker 接入 row-band v2**

`TableGridChunker.chunk()` 根据 `config.table.policy_version` 选择 planner 行为。manifest `chunk_policy` 对 v2 必须为 `table_rowband_v2`，并把 `TablePlanEntry` 的 v2 字段原样传入 `Chunk`。

- [ ] **Step 4: 运行任务测试**

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py \
  -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_structure.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: prefer full-width row bands for tables"
```

### Task 5: 升级 TableChunkParser 保留 cell span

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py`

- [ ] **Step 1: 写 span/header 失败测试**

新增断言：

- `<th>` 解析为 `is_header=True`。
- `colspan="3"` 保留为 `ParsedCell.colspan == 3`。
- `rowspan="2"` 保留为 `ParsedCell.rowspan == 2`。
- 空 `<td></td>` 保留为空文本。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py -q
```

Expected: 当前 `rows` 仍是字符串 tuple，新断言失败。

- [ ] **Step 2: 增加 `ParsedCell` 并改造 `ParsedTable.rows`**

按 3.5 的接口契约改造。为了降低一次性改动风险，保留 `header_key` 为 `tuple[str, ...]`。

- [ ] **Step 3: 更新旧 parser 测试**

旧测试中比较 rows 文本的地方，改为读取 `cell.text`。不要降低原有覆盖。

- [ ] **Step 4: 运行任务测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_parser.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py
git commit -m "feat: preserve table cell span metadata"
```

### Task 6: 升级 TableRowAssembler 纵向合并与 overlap 行去重

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py`

- [ ] **Step 1: 写纵向合并失败测试**

测试场景：

- row band 0 和 row band 1 各有表题文本和一个 table。
- 两个 row band 的第一行是同一表头。
- overlap 区域重复一行。
- 输出只保留一个表题、一个表头、一个重复行。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py -q
```

Expected: 当前 assembler 因 leading/trailing text 退回串接，新断言失败。

- [ ] **Step 2: 实现 block-aware vertical merge**

规则：

- 表题和说明文本进入 `text_blocks`，按行带顺序保留。
- `variant_kind="full_page_reference"` 的 parsed tables 只用于校验表数量和候选表题，不参与最终行拼接。
- 表格行按 `header_key` 和 row signature 去重。
- row signature 使用每行前 3 个非空 cell 文本拼接，空行不参与去重。
- 使用 `rapidfuzz.distance.Levenshtein.normalized_similarity`，相似度阈值为 `0.92`。

- [ ] **Step 3: 保留 span 渲染**

渲染时：

- `cell.is_header=True` 输出 `<th>`。
- `colspan > 1` 输出 `colspan`。
- `rowspan > 1` 输出 `rowspan`。
- 文本必须 HTML escape。

- [ ] **Step 4: 运行任务测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py
git commit -m "feat: merge table row bands with overlap dedup"
```

### Task 7: 增加横向锚定列对齐

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py`

- [ ] **Step 1: 写横向对齐失败测试**

测试场景：

- 左 chunk 行为：`年龄, 男, 女`
- 右 chunk 带重复锚定列：`年龄, 保额, 费率`
- 两侧年龄列完全一致。
- 输出行应按年龄合并，且右侧重复年龄列只保留一次。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py::test_table_row_assembler_aligns_horizontal_chunks_by_anchor_column -q
```

Expected: 失败，原因是当前 assembler 会重复保留右侧锚定列，或输出 `row_alignment_uncertain` 而没有完成横向合并。

- [ ] **Step 2: 实现 anchor alignment**

规则：

- 仅对 `cols > 1` 且存在 `anchor_bbox` 的 row band 启用。
- 每个右侧 chunk 的第一列视作锚定列候选。
- 锚定列与左侧第一列相似度均值 >= `0.90` 时合并。
- 相似度不足时输出 `row_alignment_uncertain`，保留原 chunk 表。

- [ ] **Step 3: 运行任务测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_assembler.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py
git commit -m "feat: align split table columns by anchor cells"
```

### Task 8: 强化 TableMerger 的保守 HTML 修复

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_merger.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py`

- [ ] **Step 1: 写 HTML 外壳与 span 保留失败测试**

新增断言：

- 修复破损 table 后输出不包含 `<html>` 或 `<body>` 外壳。
- 已存在的 `rowspan`、`colspan` 不被删除。
- 空 `<td></td>` 不被删除。
- 非 table 文本顺序保持在 table 前后。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py -q
```

Expected: 新断言在实现前失败。

- [ ] **Step 2: 实现保守修复**

规则：

- 只修补标签闭合和相邻重复表头。
- 不重写 cell 文本。
- 不把 HTML table 强转为 Markdown table。
- 不删除空单元格。
- 不输出 BeautifulSoup 自动补出的 `<html><body>` 外壳。

- [ ] **Step 3: 运行任务测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/table_merger.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py
git commit -m "fix: harden conservative table html repair"
```

### Task 9: 增加 table-aware QC 与 retry

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py`

- [ ] **Step 1: 写 QC 风险失败测试**

断言：

- `doc_type="table_page"`、`chunk_count=8`、`table_count=12` 触发 `table_count_explosion`。
- `extra_metrics["table_assembly_warnings"]` 包含 `row_alignment_uncertain` 或 `table_assembly_uncertain` 时触发 `table_assembly_uncertain`。
- `horizontal_split_chunks > 0` 且 `table_count >= table_count_before_assembly` 时触发 `horizontal_split_unmerged`。
- 缺少 `horizontal_split_chunks` 或 `table_count_before_assembly` 时，不触发 `horizontal_split_unmerged`。
- `table_policy == "table_rowband_v2"` 且 `table_reference_chunks == 0` 时触发 `table_reference_missing`。
- `html_broken` 仍然触发已有风险。

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py \
  -q
```

Expected: 新风险断言失败。

- [ ] **Step 2: 实现 QC 风险**

按 3.7 契约实现，风险写入 `QualityReport.risks`，指标写入 `QualityReport.metrics`。

- [ ] **Step 3: 实现 retry 映射**

规则：

- `html_broken`：`force_api=True`、`concurrency=1`。
- `table_count_explosion`：`force_api=False`、`concurrency=1`、`force_rowband=True`、`disable_horizontal_split=True`。
- `table_assembly_uncertain`：`force_api=False`、`concurrency=1`、`force_rowband=True`。
- `table_reference_missing`：`force_api=False`、`concurrency=1`、`force_rowband=True`。
- `horizontal_split_unmerged`：`force_api=False`、`concurrency=1`、`force_rowband=True`、`disable_horizontal_split=True`。
- `api_failure_ratio_high`：沿用已有低并发策略。

`force_rowband` 和 `disable_horizontal_split` 是新 retry action，必须在 Task 10 的 pipeline retry loop 中被消费；否则不要在 `RetryPlanner` 中返回这些字段。

- [ ] **Step 4: 运行任务测试**

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py \
  -q
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py
git commit -m "feat: add table v2 quality risks"
```

### Task 10: Pipeline 接入 table v2 指标并稳定收尾

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 写 pipeline 指标测试**

断言 table 页处理后 `extra_metrics` 包含：

- `table_assembled_tables`
- `table_assembly_warning_count`
- `table_count`
- `table_count_before_assembly`
- `horizontal_split_chunks`
- `table_reference_chunks`
- `table_policy`
- `table_repaired_tags`

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py \
  -q
```

Expected: 新指标断言失败。

- [ ] **Step 2: 增加 table v2 extra metrics**

在 `_process_image_once()` 中补充：

- `table_count_before_assembly`: assembly 前所有 normalized chunk Markdown 的 `<table` 计数。
- `horizontal_split_chunks`: ordered chunks 中 `risk_flags` 包含 `horizontal_split` 的数量。
- `table_reference_chunks`: ordered chunks 中 `variant_kind == "full_page_reference"` 的数量。
- `table_policy`: 当前 manifest/chunker policy，例如 `table_rowband_v2`。
- `table_count`: final repaired markdown 的 `<table` 计数。
- `table_assembly_warnings`: assembler warning 以逗号拼接。

这些指标只进入 QC metrics，不写入最终 Markdown。

- [ ] **Step 3: 让 table retry action 真正重建 chunks**

在 `_process_image()` 的 retry loop 中消费 `force_rowband` 和 `disable_horizontal_split`：

- 当 `force_rowband=True` 时，下一轮使用 `policy_version="rowband_v2"` 的临时 table 配置重新调用 `_chunk(profile, hints)`。
- 当 `disable_horizontal_split=True` 时，下一轮临时设置 `allow_horizontal_split=False`。
- 新 chunks 必须重新写 manifest，不能复用上一轮横切 manifest。
- 若 `force_api=False`，仍允许复用未变 chunk 的 API cache；但 bbox 或 image hash 变化的 chunk 必须重新请求。

- [ ] **Step 4: 稳定 QC 失败收尾**

`Pipeline.run()` 在非 dry-run 且 summary 失败时必须已经写出：

- `qc/summary.json`
- 每个文件的 `qc/{stem}.json`
- 不写误导性的最终提交 CSV。

已有行为是失败时抛 `PipelineError("quality gate failed")`，保持该异常，但不得出现 merged/qc 齐全后进程悬挂。

- [ ] **Step 5: 运行任务测试**

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py \
  -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py
git commit -m "feat: wire table v2 metrics into pipeline"
```

### Task 11: 集成测试、训练集验收与报告

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`

- [ ] **Step 1: 运行 table 相关单测**

Run:

```bash
pytest \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_image_policy.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_structure.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_parser.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_assembler.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_table_merger.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_retry_planner.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_table_assembly.py \
  -q
```

Expected: 全部通过。

- [ ] **Step 2: 运行全量单测**

Run:

```bash
pytest -q
```

Expected: 全部通过。

- [ ] **Step 3: 准备训练 table 20 张代表性 smoke 样本**

Run:

```bash
python -m scripts.chunk_eval.profile_train \
  --long-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --table-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --out-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/profile"

python -m scripts.chunk_eval.prepare_samples \
  --profile_csv "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/profile/train_profile.csv" \
  --long_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --table_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --out_root "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/sampled" \
  --manifest "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/sample_manifest.csv" \
  --per_subset 20
```

Expected:

- `sampled/table/images` 下有 20 张 table 图片软链或副本。
- `sample_manifest.csv` 中 table 样本覆盖像素分位，不依赖文件名。

- [ ] **Step 4: 运行训练 table 20 张 smoke**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/sampled/table/images" \
  --output_csv "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/submission.csv" \
  --work_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/run" \
  --config "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_v2.yaml"
```

若 QC 阻断导致正式 CSV 未写出，使用 merged 兜底只用于诊断，不作为可提交产物。

- [ ] **Step 5: smoke 离线评分**

只在 `submission.csv` 已生成时运行本步骤。若 smoke 被 QC 阻断，先查看 `run/qc/summary.json` 和 `merged/*.md`，不要把兜底 CSV 作为达标依据。

Run:

```bash
python -m finix_restore.eval.cli \
  --pred "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/submission.csv" \
  --gt "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --output "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_smoke_20/metrics.json"
```

Expected:

- `mean_overall >= 55`
- `mean_text_edit <= 0.25`
- `mean_table_teds >= 35`
- `mean_read_order_edit <= 0.50`
- `html_broken = 0`

- [ ] **Step 6: 训练 table 全量**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --output_csv "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/submission.csv" \
  --work_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/run" \
  --config "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_v2.yaml"
```

Expected:

- 进程正常退出。
- `submission.csv` 存在，除非 QC 明确阻断。
- `run/qc/summary.json` 存在。
- 没有 API 密钥写入日志。

- [ ] **Step 7: 全量评分与 CSV 校验**

本步骤必须使用正式 `submission.csv`。如果 QC 阻断导致该文件不存在，本轮全量验收失败，应先处理 QC 风险。

Run:

```bash
python /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py \
  --csv "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/submission.csv" \
  --expected-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --qc-summary "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/run/qc/summary.json" \
  --fail-on-risk html_broken \
  --fail-on-risk api_failure_ratio_high \
  --out "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/validate_report.json"

python -m finix_restore.eval.cli \
  --pred "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/submission.csv" \
  --gt "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --output "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/metrics.json"
```

Expected:

- validate report `passed = true`
- `mean_overall >= 60`
- `mean_text_edit <= 0.20`
- `mean_table_teds >= 40`
- `mean_read_order_edit <= 0.40`

- [ ] **Step 8: 生成 table 失败分析报告**

Run:

```bash
python /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py \
  --metrics "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/metrics.json" \
  --pred "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/submission.csv" \
  --gt-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --run-dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/run" \
  --out "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/table_v2_full_train/table_failure_summary.md"
```

Expected:

- 报告列出 Top 10 最差样本。
- 报告列出 chunk shape 分布。
- 报告列出长度比分位数。
- 报告列出 table count 差异。

- [ ] **Step 9: 更新实验记录**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md` 追加：

- table v2 配置路径。
- smoke 和 full train 命令。
- 指标结果。
- 风险统计。
- 未达标样本的共同失败模式。

- [ ] **Step 10: 提交**

```bash
git add \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md
git commit -m "docs: record table v2 evaluation results"
```

## 5. 自检清单

实施者完成每个任务后检查：

- 没有修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data`。
- 没有打印或提交 `.env`、`FINIX_API_KEY`、`apiKey`。
- 没有新增 FinixDoc-VL 以外的模型/API 调用。
- 没有按文件名写训练集/A 榜/B 榜特判。
- 新增配置有默认值，旧配置仍可运行。
- table v2 可通过配置关闭。
- CSV 校验覆盖列名、行数、重复文件名、空输出。
- table 全量训练集评分达到 60+ 后，才允许进入 A 榜生成。

## 6. 实施顺序建议

推荐按任务顺序执行。Task 1 到 Task 4 先解决“输入形态与切片破坏结构”的问题；Task 5 到 Task 8 再解决“表格结构重建与 HTML 合法化”的问题；Task 9 到 Task 11 最后做风险闭环和全量验收。

不要先调 API 并发或 HTML 修补作为主要优化手段。当前瓶颈是内容完整性、表格碎片化和 row-level assembly，工程稳定性是并行必修项，但不是 table 60+ 的主要得分来源。
