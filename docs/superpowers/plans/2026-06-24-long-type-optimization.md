# Long Type Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将训练集 `long_strip` 全量评分从当前 `Overall 64.35` 提升到 `80+`，同时保持赛题约束下只调用 FinixDoc-VL，不引入其他外部大模型、VLM 或 OCR API。

**Architecture:** 保持现有 `finix_restore` pipeline 主干，针对 long 路径新增长图专用空白带检测、long 内嵌表格合并、Markdown 块形态归一化和评测诊断。`LayoutSentry` 只产出版面提示，`LongStripChunker` 继续负责切块，新增 `LongStripMerger` 负责 long 的跨 chunk 文本/表格合并，最终仍由 `QualityGate` 与离线 scorer 验收。

**Tech Stack:** Python 3.12, dataclasses, Pillow/numpy, BeautifulSoup/lxml, rapidfuzz, pandas, pytest, existing `finix_restore.eval` scorer, existing FinixDoc-VL client only.

---

## 0. 背景、目标与强约束

证据来源：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/阶段性实验背景总结-20260624.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/full_train_balanced_6m_20260624/long/metrics.json`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/full_train_balanced_6m_20260624/long/submission.csv`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_long_100/mds`

当前训练集 long 全量基线：

| 指标 | 当前值 |
| --- | ---: |
| `file_count` | 100 |
| `mean_text_edit` | 0.0832 |
| `mean_table_teds` | 43.31 |
| `mean_read_order_edit` | 0.7143 |
| `mean_overall` | 64.35 |

关键诊断：

- 无表 long：52 张，均分约 `73.64`。
- 含表 long：48 张，均分约 `54.28`。
- 48 个含表 long 中 34 个预测表格数量与 GT 不一致，常见为 1 个 GT 表被切成 2 到 4 个预测表。
- 当前 long manifest 中 `cut_source=fixed_cut` 覆盖训练集 2040 个 chunk，说明空白带切线基本没有生效。
- 现有 `LayoutSentry(max_thumb_size=1200)` 对极长图按最长边缩略，1500 x 80000 级图片会被压到约 20px 宽，水平空白带检测失真。

训练集 long 80+ 的组合目标：

| 分量 | 验收目标 |
| --- | ---: |
| `mean_text_edit` | `<= 0.07`，不得高于当前 0.0832 |
| 含表 long `mean_table_teds` | `>= 90`，理想 `>= 95` |
| `mean_read_order_edit` | `<= 0.50`，理想 `<= 0.47` |
| `mean_overall` | `>= 80.00` |

强约束：

- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data` 下原始样本。
- 不读取、打印、复制或提交 `.env` 中的真实密钥。
- 不调用 FinixDoc-VL 之外的任何大模型、VLM 或 OCR API。
- 不按训练集、A 榜、B 榜文件名写特判逻辑。
- 运行产物只进入 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs`。
- 计划文档只放接口契约、关键小片段和关键 diff；大段完整实现进入代码文件和 PR diff。

### 0.1 审核修订摘要

本计划经审核后修正以下执行风险：

- 将 `blank_cut_ratio`、`fixed_cut_count` 等切线指标明确为 pipeline 从 `chunks` 计算后通过 `extra_metrics` 写入 QC，避免把无法从 markdown 推导的指标放进 `QualityGate` 内部计算。
- 将 Task 2 的首个失败测试从“chunker 会选择空白带”改为“dry-run QC 会记录切线统计”。前者在当前 `LongStripChunker` 给定 hints 时已经可能通过，不能作为有效 TDD 红灯。
- 补充 `configs/default.yaml` 与 `scripts/chunk_eval/configs/balanced_6m.yaml` 的显式配置步骤，避免文件结构里列出修改文件但任务里没有落点。
- 明确 `LongStripMerger` 通过组合 `DedupMerger` 获得文本 overlap 能力；long 路由不再先单独执行一次 `DedupMerger`，避免重复去重或误删表格片段。
- 明确 Markdown 列表项升标题只允许在目录块或标题密集块中发生，避免把正文枚举项误改成标题。

## 1. 文件结构

新增文件：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_layout.py`
  - 长图专用空白带检测，避免极长图缩略宽度过小。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_merger.py`
  - long 路径的文本接缝去重、内嵌表格续接和风险输出。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/analyze_long_metrics.py`
  - 对 long 训练集 metrics、submission、GT 和 manifest 做分桶诊断。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_long_layout.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_long_merger.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_analyze_long_metrics.py`

修改文件：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
  - 给 `LongChunkConfig` 增加长图空白带检测参数，保持默认值向后兼容。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/layout_sentry.py`
  - 对 long 图像使用 `LongBlankBandDetector`，接口仍返回 `LayoutHints`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
  - 保持 `LongStripChunker.chunk()` 公共接口，补充 manifest 中的切线统计。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/normalizer.py`
  - 增加保守 Markdown 块形态归一化。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py`
  - 增加逻辑块级 fuzzy overlap 去重，继续保护目录和表格。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - long 路径改用 `LongStripMerger`，table_page 路径保持现有 table assembler；同时计算 long 专属 QC 指标，并通过 `extra_metrics` 交给现有 `QualityGate.check_file()` 写入报告。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/balanced_6m.yaml`
- 相关测试：
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_layout_sentry.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_normalizer.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_dedup.py`
  - `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

## 2. 接口契约

### 2.1 `LongChunkConfig`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`

新增字段必须有默认值，避免旧 YAML 和旧测试失效。

关键 diff：

```python
@dataclass(frozen=True)
class LongChunkConfig:
    target_pixels: int = 6_000_000
    safe_max_pixels: int = 8_000_000
    max_window_height: int = 4000
    min_window_height: int = 1800
    vertical_overlap: int = 320
    blank_band_search_px: int = 360
    blank_band_thumb_width: int = 256
    blank_band_max_thumb_height: int = 40000
    blank_band_density_threshold: float = 0.006
    blank_band_min_height_px: int = 50
```

契约：

- `blank_band_thumb_width` 是长图检测保留的缩略宽度，不使用最长边上限。
- `blank_band_max_thumb_height` 控制内存与运行时间，不能导致原图全尺寸加载到 numpy。
- `blank_band_density_threshold` 只用于切线候选检测，不改变最终 OCR 文本。
- `blank_band_min_height_px` 是原图坐标下的最小空白带高度。
- `configs/default.yaml` 与 `scripts/chunk_eval/configs/balanced_6m.yaml` 应显式写入这些 long 参数；未写入时 dataclass 默认值仍必须生效。

### 2.2 `LongBlankBandDetector`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_layout.py`

公共接口：

```python
@dataclass(frozen=True)
class LongBlankBandDetection:
    crop_box: tuple[int, int, int, int]
    horizontal_blank_bands: list[tuple[int, int]]
    scale: float
    thumb_size: tuple[int, int]

class LongBlankBandDetector:
    def detect(self, image_path: Path, config: LongChunkConfig) -> LongBlankBandDetection:
        """Return long-strip crop box and horizontal blank bands in original coordinates."""
```

契约：

- 输出坐标必须是原图坐标。
- 空白带按 `(start_y, end_y)` 升序，互不重叠。
- 不写文件，不调用 API。
- 对低对比度或全白图返回空空白带，但 `crop_box` 必须覆盖原图。
- 检测只使用本地图像投影，不使用 GT 或文件名。

### 2.3 `LayoutSentry`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/layout_sentry.py`

公共接口保持：

```python
class LayoutSentry:
    def analyze(self, image_path: Path, chunk_config: ChunkConfig | None = None) -> LayoutHints
```

兼容规则：

- `chunk_config` 可选；为空时使用 `ChunkConfig()`。
- `LayoutSentry.__init__()` 可以新增 `long_detector: LongBlankBandDetector | None = None` 可选参数，默认实例化 `LongBlankBandDetector()`，方便单测注入。
- 对 `height / width >= 10` 或 `height >= 30000` 的图像，水平空白带来自 `LongBlankBandDetector`。
- table_page 和 normal_page 仍使用现有缩略投影逻辑。
- `LayoutHints` 数据结构不新增字段，避免大范围修改调用方。

### 2.4 `LongStripMerger`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_merger.py`

公共接口：

```python
@dataclass(frozen=True)
class LongMergeResult:
    markdown: str
    warnings: Sequence[str]
    merged_tables: int
    removed_table_fragments: int
    removed_text_blocks: int

class LongStripMerger:
    def merge(self, ordered_chunks: Sequence[ChunkText]) -> LongMergeResult:
        """Merge long-strip chunks with text dedup and embedded-table continuation handling."""
```

契约：

- 输入必须已经按阅读顺序排序。
- 只处理 `doc_type == "long_strip"` 的合并；table_page 继续走 `TableRowAssembler`。
- `LongStripMerger` 内部组合 `DedupMerger` 处理文本 overlap，组合 `TableChunkParser` 识别 HTML table 片段；pipeline 不应在 long 路由上先额外执行一次 `DedupMerger`。
- 对相邻 chunk 的连续表格，只有在表头 key、列数或行 key 能对齐时才合并。
- 对齐不确定时保留原 chunk 顺序，并输出 `long_table_alignment_uncertain` warning。
- 不改写金额、百分比、备案号、条款号。
- 输出必须以单个换行结尾；空输入输出空字符串。

### 2.5 long 专属 QC 指标

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`

指标由 pipeline 根据 `chunks` 和 `LongMergeResult` 计算，并通过 `QualityGate.check_file()` 的 `extra_metrics` 参数写入现有 QC JSON。

指标契约：

| 指标 | 类型 | 来源 | 说明 |
| --- | --- | --- | --- |
| `blank_cut_count` | int | `Chunk.cut_source` | 非最后 long chunk 中 `cut_source == "blank_band"` 的数量。 |
| `fixed_cut_count` | int | `Chunk.cut_source` | 非最后 long chunk 中非 `blank_band` 的数量。 |
| `blank_cut_ratio` | float | 上两项 | `blank_cut_count / max(1, blank_cut_count + fixed_cut_count)`。 |
| `long_merged_tables` | int | `LongMergeResult` | long 路径合并出的跨 chunk 表格数量。 |
| `long_removed_table_fragments` | int | `LongMergeResult` | 合并后删除的重复表格片段数量。 |
| `long_merge_warning_count` | int | `LongMergeResult` | long 合并 warning 数。 |

### 2.6 `MarkdownNormalizer`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/normalizer.py`

新增行为只允许改 Markdown 标记，不允许改金融内容。

允许规则：

- `**第一条** 正文` -> `第一条 正文`
- `* 1.1 合同构成` 只允许在目录块或标题密集块中转为标题行；普通正文列表保持列表。
- `# # 1.1 标题` 继续使用现有坏标题修复。
- `##1.1` -> `## 1.1`

禁止规则：

- 不改金额、费率、百分比、日期、备案号。
- 不做简繁转换。
- 不把 HTML 表格强制转为管道表。
- 不根据训练集文件名定制任何规则。

### 2.7 `analyze_long_metrics.py`

文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/analyze_long_metrics.py`

CLI 契约：

```bash
python scripts/chunk_eval/analyze_long_metrics.py \
  --metrics outputs/chunk_eval/full_train_balanced_6m_20260624/long/metrics.json \
  --submission outputs/chunk_eval/full_train_balanced_6m_20260624/long/submission.csv \
  --gt-dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --manifest-dir outputs/chunk_eval/full_train_balanced_6m_20260624/long/run/chunks \
  --out-json outputs/chunk_eval/long_optimization_diagnostics/breakdown.json \
  --out-md outputs/chunk_eval/long_optimization_diagnostics/breakdown.md
```

输出必须包含：

- 总体指标。
- 有表/无表分桶。
- 表格数量匹配/不匹配分桶。
- 表格数量必须通过 `finix_restore.eval.tables.extract_tables()` 计算，不使用临时正则重复实现。
- `blank_cut_ratio`、`fixed_cut_count` 分布。
- 最差 20 个样本列表。
- 训练集 80+ 目标的分量缺口估算。

## 3. 任务分解

### Task 1: 长图专用空白带检测

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_layout.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_long_layout.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/layout_sentry.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_layout_sentry.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py`

- [ ] **Step 1: 写失败测试，证明极长图不能被最长边缩略抹掉空白带**

测试名：`test_long_blank_detector_preserves_horizontal_bands_on_extreme_aspect`

测试构造：

- 生成 `300 x 6000` 的白底图片。
- 在 `0..2400` 和 `3600..6000` 画黑色文本块。
- 中间 `2400..3600` 留白。
- 断言 `LongBlankBandDetector.detect()` 返回的空白带包含 y=3000。
- 断言 `thumb_size[0] == 256`。

Run:

```bash
pytest tests/test_long_layout.py::test_long_blank_detector_preserves_horizontal_bands_on_extreme_aspect -q
```

Expected: FAIL，原因是 `finix_restore.long_layout` 尚不存在。

- [ ] **Step 2: 实现 `LongBlankBandDetector` 最小版本**

实现要点：

- 使用 `PIL.Image.open()` 读取尺寸和灰度。
- 缩略比例为 `min(config.blank_band_thumb_width / width, config.blank_band_max_thumb_height / height, 1.0)`。
- 使用 `arr < 245` 得到 ink mask。
- 用行墨迹密度 `<= blank_band_density_threshold` 找空白带。
- 将空白带映射回原图坐标，并过滤小于 `blank_band_min_height_px` 的带。

- [ ] **Step 3: 运行 long detector 单测**

Run:

```bash
pytest tests/test_long_layout.py -q
```

Expected: PASS。

- [ ] **Step 4: 将 `LayoutSentry` 接入 long detector**

关键 diff 形态：

```python
if _is_long_strip_shape(width, height):
    long_detection = self.long_detector.detect(image_path, chunk_config.long)
    return LayoutHints(
        crop_box=long_detection.crop_box,
        horizontal_blank_bands=long_detection.horizontal_blank_bands,
        vertical_blank_bands=[],
        table_line_density=0.0,
        column_count=1,
    )
```

兼容要求：

- `LayoutSentry().analyze(path)` 不传配置仍能工作。
- 旧的普通页空白带测试继续通过。

- [ ] **Step 5: 跑相关测试**

Run:

```bash
pytest tests/test_long_layout.py tests/test_layout_sentry.py tests/test_chunk_config.py -q
```

Expected: PASS。

- [ ] **Step 6: 显式更新 long 配置**

修改：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/balanced_6m.yaml`

关键 YAML 片段：

```yaml
chunk:
  long:
    blank_band_thumb_width: 256
    blank_band_max_thumb_height: 40000
    blank_band_density_threshold: 0.006
    blank_band_min_height_px: 50
```

验收：

- `ChunkConfig.from_mapping()` 能读取这些值。
- 删除 YAML 中这些键时，dataclass 默认值仍生效。

### Task 2: 让 long 切块真正使用空白带并输出切线统计

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 写失败测试，证明 dry-run QC 会记录 long 切线统计**

测试名：`test_dry_run_qc_records_long_cutline_metrics`

测试构造：

- 构造一个最小 `Pipeline` dry-run 配置。
- 构造 3 个 long `Chunk`：前两片分别为 `blank_band` 和 `fixed_cut`，最后一片为文档尾部。
- 调用 `_write_dry_run_qc(profile, chunks)`。
- 读取 `qc/{stem}.json`。
- 断言 `blank_cut_count == 1`、`fixed_cut_count == 1`、`blank_cut_ratio == 0.5`。

Run:

```bash
pytest tests/test_pipeline_quality_blocking.py::test_dry_run_qc_records_long_cutline_metrics -q
```

Expected: FAIL，原因是现有 dry-run QC 未写入 long 切线统计。

- [ ] **Step 2: 修改 `Pipeline._process_image()` 调用**

关键 diff：

```python
hints = self.layout_sentry.analyze(image_path, chunk_config=self.config.chunk)
```

- [ ] **Step 3: 增加 long 切线统计 helper**

新增私有 helper：

签名：`_long_cutline_metrics(self, chunks: Sequence[Chunk], doc_type: DocType) -> dict[str, float | int]`

要求：

- `doc_type != "long_strip"` 时返回空 dict。
- 最后一片不计入 `fixed_cut_count`。
- helper 同时供 `_write_dry_run_qc()` 和 `_process_image_once()` 使用，避免 dry-run 与真实运行统计口径不一致。

- [ ] **Step 4: 增加 long dry-run/QC 切线统计**

指标名称：

- `blank_cut_count`
- `fixed_cut_count`
- `blank_cut_ratio`

计算规则：

- 只统计 `doc_type == "long_strip"`。
- 最后一片如果 `cut_source == "fixed_cut"`，不计为失败，因为它落在文档尾部。
- `blank_cut_ratio = blank_cut_count / max(1, blank_cut_count + fixed_cut_count)`。

- [ ] **Step 5: 补充 chunker 回归测试**

测试名：`test_long_chunker_marks_blank_band_cut_when_hint_near_target`

测试要求：

- 使用真实临时图片路径，因为 `LongStripChunker.chunk()` 会读取 sha1 并保存 crop。
- 构造 `LayoutHints(horizontal_blank_bands=[(3920, 4080), (7920, 8080)])`。
- 断言至少一个非最后 chunk 的 `cut_source == "blank_band"`。
- 该测试在 Task 1 完成后可能直接 PASS；若直接 PASS，将其视为回归覆盖，不作为阻塞。

- [ ] **Step 6: 跑相关单测**

Run:

```bash
pytest tests/test_chunkers.py tests/test_pipeline_quality_blocking.py -q
```

Expected: PASS。

- [ ] **Step 7: 跑训练集 long dry-run 验收**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --output_csv outputs/chunk_eval/long_blank_cut_dry_run/submission.csv \
  --work_dir outputs/chunk_eval/long_blank_cut_dry_run/run \
  --config scripts/chunk_eval/configs/balanced_6m.yaml \
  --dry_run
```

Expected:

- `outputs/chunk_eval/long_blank_cut_dry_run/run/chunks/*/manifest.json` 正常生成。
- `over_hard_chunks == 0`。
- 训练集 long 的 `blank_cut_ratio` 均值 `>= 0.85`。

### Task 3: long 内嵌表格续接与合并

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/long_merger.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_long_merger.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`

- [ ] **Step 1: 写失败测试，证明同一表跨 chunk 会合并为一个表**

测试名：`test_long_merger_merges_adjacent_table_fragments_with_same_header`

测试构造：

- chunk A：正文 + `<table>`，表头为 `责任/说明`，第一行数据为 `住院/给付`。
- chunk B：重复表头 `责任/说明`，第二行数据为 `门诊/给付` + 后文。
- 两个 chunk 坐标有纵向 overlap。

断言：

- 输出中 `<table` 只出现 1 次。
- `住院` 和 `门诊` 都保留。
- 重复表头只保留一次。
- `merged_tables == 1`。

Run:

```bash
pytest tests/test_long_merger.py::test_long_merger_merges_adjacent_table_fragments_with_same_header -q
```

Expected: FAIL，原因是 `LongStripMerger` 尚不存在。

- [ ] **Step 2: 写失败测试，证明不确定表格不硬合并**

测试名：`test_long_merger_preserves_distinct_tables_when_headers_differ`

断言：

- 输出中 `<table` 出现 2 次。
- warnings 包含 `long_table_alignment_uncertain`。
- 原始 chunk 顺序不变。

- [ ] **Step 3: 实现 `LongStripMerger`**

实现要点：

- 构造函数接收可选 `dedup: DedupMerger | None = None` 与 `table_parser: TableChunkParser | None = None`，默认使用现有实现。
- 复用 `TableChunkParser` 的单元格解析能力。
- 对相邻 chunk 的 table 片段计算 `header_key` 和列数。
- 只在 `header_key` 相同或列数相同且首列行 key 连续时合并。
- 合并后用合法 HTML table 输出。
- 文本 overlap 委托 `DedupMerger`；`LongStripMerger` 自己不再实现第二套文本去重算法。

- [ ] **Step 4: 接入 pipeline long 路由**

关键 diff：

```python
if profile.doc_type == "table_page":
    assembled = self.table_assembler.assemble(ordered)
    repaired = self.table_merger.repair(assembled.markdown)
elif profile.doc_type == "long_strip":
    merged = self.long_merger.merge(ordered)
    repaired = self.table_merger.repair(merged.markdown)
else:
    merged = self.dedup.merge(ordered)
    repaired = self.table_merger.repair(merged.markdown)
```

额外 QC 指标：

- `long_merged_tables`
- `long_removed_table_fragments`
- `long_merge_warning_count`

写入方式：

- `_process_image_once()` 从 `LongMergeResult` 取值。
- 指标合并进 `extra_metrics`。
- `QualityGate.check_file()` 使用现有 `extra_metrics` 机制写入文件级 QC，不需要新增 QualityGate 内部规则。

- [ ] **Step 5: 跑 long merger 和 pipeline 相关测试**

Run:

```bash
pytest tests/test_long_merger.py tests/test_pipeline_table_assembly.py tests/test_quality_gate.py -q
```

Expected: PASS。

### Task 4: Markdown 块形态归一化

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/normalizer.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_normalizer.py`

- [ ] **Step 1: 写失败测试，覆盖加粗条款编号归一化**

测试名：`test_normalizer_removes_bold_marker_from_article_prefix_only`

输入输出：

- 输入：`**第一条** 本保险合同由保险条款组成。`
- 输出：`第一条 本保险合同由保险条款组成。\n`
- 断言 `100%`、`C000002`、`2026年6月24日` 这类内容不被改写。

- [ ] **Step 2: 写失败测试，覆盖列表项误判标题**

测试名：`test_normalizer_promotes_numbered_list_title_in_toc_context`

输入输出：

- 输入：`# 条款目录\n\n* 1. 总则\n* 1.1 合同构成`
- 输出中包含 `## 1. 总则` 和 `### 1.1 合同构成`。
- 另加负例：`- 1. 没有指定受益人` 在普通正文中仍保持列表，不升为标题。

- [ ] **Step 3: 实现保守样式归一化**

关键约束：

- 仅处理行首 Markdown 标记。
- 仅当行首编号符合 `第X条`、`1.`、`1.1`、`（一）`、`(一)`、`①` 时参与标题层级判断。
- 只有当同一块前 3 行包含 `目录`，或同一块内编号标题候选不少于 3 行时，才允许将 `* 1.1` / `- 1.1` 这类列表项升为标题。
- 不处理行中数字和金融字段。

- [ ] **Step 4: 跑 normalizer 测试**

Run:

```bash
pytest tests/test_normalizer.py -q
```

Expected: PASS。

### Task 5: 逻辑块级接缝去重

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_dedup.py`

- [ ] **Step 1: 写失败测试，证明相邻重复标题块只保留一次**

测试名：`test_block_level_overlap_removes_fuzzy_duplicate_heading_once`

测试构造：

- 前一 chunk 尾部：`## 2.3 等待期`
- 后一 chunk 头部：`## 2.3等待期`
- 两个 chunk 坐标有 overlap。

断言：

- 合并结果中等待期标题只出现一次。
- 目录块中的同名标题仍按现有测试保留。

- [ ] **Step 2: 写失败测试，证明正文块 fuzzy 重复可删但表格不删**

测试名：`test_block_level_overlap_keeps_table_fragments_for_long_merger`

断言：

- 普通段落重复被去重。
- `<table>` 片段不由 `DedupMerger` 删除，交给 `LongStripMerger` 处理。

- [ ] **Step 3: 实现块级 overlap**

实现要点：

- 只在 `_chunks_overlap()` 为真时启用。
- 先按 `BlockSegmenter.segment()` 取尾部 3 个块和头部 3 个块。
- 对标题和段落用规范化文本比较，阈值从 `similarity_threshold` 复用。
- `_PROTECTED_BLOCKS` 仍保持 `toc/table/header_footer`。

- [ ] **Step 4: 跑 dedup 测试**

Run:

```bash
pytest tests/test_dedup.py -q
```

Expected: PASS。

### Task 6: long 诊断脚本

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/analyze_long_metrics.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_analyze_long_metrics.py`

- [ ] **Step 1: 写失败测试，覆盖有表/无表和表数量匹配分桶**

测试名：`test_analyze_long_metrics_reports_table_count_mismatch`

测试 fixture：

- 一个无表样本，overall 80。
- 一个有表样本，GT 1 个 table，预测 2 个 table。

断言输出 JSON：

- `total.file_count == 2`
- `by_has_table.true.file_count == 1`
- `table_count_mismatch.file_count == 1`
- `table_count_mismatch.mean_table_teds` 来自 metrics JSON，而不是重新评分。

- [ ] **Step 2: 实现 CLI**

实现要点：

- 使用 `argparse`。
- 使用 pandas 读取 submission。
- 从 `gt-dir` 读取同名 `.md`。
- 从 manifest 读取 `cut_source` 统计。
- 使用 `finix_restore.eval.tables.extract_tables()` 计算 GT/预测表格数量。
- 输出 JSON 和 Markdown，目录不存在时创建。

- [ ] **Step 3: 跑脚本测试**

Run:

```bash
pytest tests/test_chunk_eval_analyze_long_metrics.py -q
```

Expected: PASS。

- [ ] **Step 4: 对当前基线生成诊断报告**

Run:

```bash
python scripts/chunk_eval/analyze_long_metrics.py \
  --metrics outputs/chunk_eval/full_train_balanced_6m_20260624/long/metrics.json \
  --submission outputs/chunk_eval/full_train_balanced_6m_20260624/long/submission.csv \
  --gt-dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --manifest-dir outputs/chunk_eval/full_train_balanced_6m_20260624/long/run/chunks \
  --out-json outputs/chunk_eval/long_optimization_diagnostics/baseline_breakdown.json \
  --out-md outputs/chunk_eval/long_optimization_diagnostics/baseline_breakdown.md
```

Expected:

- 输出报告存在。
- 报告复现当前含表 long 低分和表数量不匹配现象。

### Task 7: smoke、全量评分与回归门禁

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`
- 本任务不新增代码文件；若前序任务调整诊断脚本字段名，只同步实验记录中的字段引用。

- [ ] **Step 1: 跑单测全量**

Run:

```bash
pytest -q
```

Expected: PASS。

- [ ] **Step 2: 跑格式与静态 diff 检查**

Run:

```bash
git diff --check
```

Expected: no output, exit 0。

- [ ] **Step 3: 跑 long 10 张 smoke**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --output_csv outputs/chunk_eval/long_optimization_smoke_10/submission.csv \
  --work_dir outputs/chunk_eval/long_optimization_smoke_10/run \
  --config scripts/chunk_eval/configs/balanced_6m.yaml \
  --limit 10 \
  --image_concurrency 1
```

评分：

```bash
python -m finix_restore.eval.cli \
  --pred outputs/chunk_eval/long_optimization_smoke_10/submission.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --output outputs/chunk_eval/long_optimization_smoke_10/metrics.json
```

Expected:

- CSV 可读，列名为 `file_name,ground_truth`。
- 行数 10，无重复文件名，无空输出。
- `mean_overall >= 72`。
- `mean_read_order_edit` 低于当前 smoke `0.6347`。
- 含表样本 `mean_table_teds` 高于当前 smoke `41.89`。

- [ ] **Step 4: 跑训练集 long 全量**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --output_csv outputs/chunk_eval/long_optimization_full_train/submission.csv \
  --work_dir outputs/chunk_eval/long_optimization_full_train/run \
  --config scripts/chunk_eval/configs/balanced_6m.yaml \
  --image_concurrency 5
```

评分：

```bash
python -m finix_restore.eval.cli \
  --pred outputs/chunk_eval/long_optimization_full_train/submission.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --output outputs/chunk_eval/long_optimization_full_train/metrics.json
```

格式校验：

```bash
python scripts/chunk_eval/validate_submission.py \
  --csv outputs/chunk_eval/long_optimization_full_train/submission.csv \
  --expected-dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images"
```

Expected:

- CSV 校验通过。
- `file_count == 100`。
- `mean_overall >= 80.00`。
- `mean_text_edit <= 0.07`。
- `mean_read_order_edit <= 0.50`。
- `blank_cut_ratio` 均值 `>= 0.85`。

- [ ] **Step 5: 生成全量 long 诊断报告**

Run:

```bash
python scripts/chunk_eval/analyze_long_metrics.py \
  --metrics outputs/chunk_eval/long_optimization_full_train/metrics.json \
  --submission outputs/chunk_eval/long_optimization_full_train/submission.csv \
  --gt-dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --manifest-dir outputs/chunk_eval/long_optimization_full_train/run/chunks \
  --out-json outputs/chunk_eval/long_optimization_full_train/long_breakdown.json \
  --out-md outputs/chunk_eval/long_optimization_full_train/long_breakdown.md
```

Expected:

- `by_has_table.true.mean_table_teds >= 90`。
- `table_count_mismatch.file_count <= 5`。
- 最差 20 样本列表可用于下一轮人工审计。

- [ ] **Step 6: 记录实验**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md` 追加一条实验记录，包含：

- 输入目录。
- 配置文件。
- work_dir。
- submission CSV。
- metrics JSON。
- `analyze_long_metrics.py` 诊断 JSON/MD。
- 与基线 `64.35` 的差异。

## 4. 最终验收清单

代码验收：

- `pytest -q` 通过。
- `git diff --check` 通过。
- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data`。
- 不新增除 FinixDoc-VL 以外的模型/API 调用。
- 不打印 `.env`、`apiKey`、`userIds`。

训练集 long 验收：

- `outputs/chunk_eval/long_optimization_full_train/submission.csv` 可被 pandas 正常读取。
- CSV 列名正确：`file_name`、`ground_truth`。
- 行数 100。
- 无重复文件名。
- 无空输出。
- `metrics.json` 中 `mean_overall >= 80.00`。
- `analyze_long_metrics.py` 报告中含表 long `mean_table_teds >= 90`。
- `mean_read_order_edit <= 0.50`。

A 榜 long 风险验收：

- 对 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC A榜评测数据集/finix_huge_long_rest_A/images` dry-run，`over_hard_chunks == 0`。
- A 榜 long 预测 QC 无 `empty_output`、`api_failure_ratio_high`、`high_duplication`。
- 不依赖 A 榜文件名做任何特殊逻辑。

## 5. 自检记录

计划覆盖：

- 目标：已覆盖 long 训练集 80+ 的分量目标和最终指标。
- 架构：已覆盖 `LayoutSentry`、`LongStripChunker`、`LongStripMerger`、`MarkdownNormalizer`、`DedupMerger`、`QualityGate` 的职责边界。
- 文件路径：已列出新增与修改文件的绝对路径。
- 接口契约：已定义 `LongChunkConfig`、`LongBlankBandDetector`、`LayoutSentry`、`LongStripMerger`、`analyze_long_metrics.py`。
- 测试：每个开发任务都有测试名和运行命令。
- 验收：已覆盖单测、CSV 格式、训练集 long 指标、A 榜 long 风险。

占位扫描：

- 本计划不包含未定占位语、延期实现提示或面向测试文件名的特判要求。
- 本计划只包含小段接口与关键 diff，不包含大段完整实现。
