# Image Chunking Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 MVP 图片切分升级为“分类型像素预算 + 内容区裁剪 + 版面感知切线 + 可审计 manifest”的稳定切分链路，降低 FinixDoc-VL 请求数与超时风险，并减少表格/长条接缝截断。

**Architecture:** 保持现有 `ImageProfiler -> LayoutSentry -> Chunker -> FinixApiClient -> Pipeline` 主链路，只在切分配置、几何工具、chunk 元数据和 dry-run 统计处做小而集中的扩展。`LayoutSentry` 已有的 `crop_box`、水平/垂直空白带和 `table_line_density` 进入 `LongStripChunker`、`TableGridChunker`、`PageChunker`，所有输出仍通过 `{work_dir}/chunks/{stem}/manifest.json` 与现有 API cache 串联。

**Tech Stack:** Python 3.12、Pillow、numpy、PyYAML、pytest；唯一 VLM/API 仍为 FinixDoc-VL。

---

## 0. 审核修订记录

本次审核发现并修正以下计划问题：

- 原计划把 `RunConfig.chunk` 直接改成 `ChunkConfig`，但仓库中 `tests/test_cli_sampling.py`、`tests/test_submission.py`、`tests/test_pipeline_quality_blocking.py` 都直接用旧扁平 dict 构造 `RunConfig`。现改为要求 `RunConfig.__post_init__()` 兼容旧扁平 dict，并把这些测试纳入 Task 1 验收。
- 原计划要求更新 `configs/default.yaml` 为嵌套 schema，但没有同步更新 `tests/test_chunkers.py::test_default_table_config_splits_15m_pixel_pages_for_api_stability` 的断言。现明确改为嵌套 key 断言。
- 原计划的 table overlap 像素预算用例在 `target=6M/safe=8M` 下不一定失败，无法证明 overlap 已计入预算。现改为 `target=6M/safe=6M` 的专门单测，确保旧算法会暴露问题。
- 原计划没有定义 `TableGridChunker`、`PageChunker` 的 `config=` 构造器兼容契约，执行到 Task 4/5 会出现接口歧义。现补充三类 chunker 的构造器兼容规则。
- 原计划 dry-run QC 测试放在 `tests/test_pipeline_quality_blocking.py`，但现有 dry-run 端到端测试实际在 `tests/test_submission.py`。现将 dry-run 指标测试挂到 `test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv`。
- 原计划提到 `overlap_dict()` 但没有给出函数签名和断言；`traceable_chunk_name()` 也没有测试。现补齐几何工具契约。

## 1. 需求来源与强约束

需求来源：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/图片切分优化方案.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/赛题数据统计分析.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/FinixDoc-VL的图片尺寸说明.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/Task2复杂金融文档还原挑战.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/FinixDoc-VL的API调用说明.md`
- 当前源码目录：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore`

强约束：

- 不接入 FinixDoc-VL 以外的大模型或 VLM API。
- 不读取、打印或写入 `.env` 中真实密钥；配置快照继续脱敏 `api_key`。
- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data` 下原始样本。
- 不按训练/A榜/B榜文件名写特判逻辑；所有策略只依赖尺寸、像素、长宽比、版面提示和配置。
- 计划文档只放关键小段代码或小 diff；完整实现进入代码仓库和 PR。

非目标：

- 不重写 `FinixApiClient` 请求协议。
- 不重写 dedup、table merger、reading order 的核心算法。
- 不新增外部 OCR、表格识别模型或 GPU 依赖。
- 不把 `outputs/` 运行产物纳入提交。

## 2. 当前代码差距

当前关键文件：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
  - `chunk.max_chunk_pixels=4000000` 名称像“硬上限”，但实际 `TableGridChunker` 加 overlap 后可超过该值。
  - `long_window_height=4000` 对 1500px 宽图约 6M，实际已高于 `max_chunk_pixels`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
  - `Chunk` 只含基础 `bbox/row/col/overlap/image_sha1`，缺少 `chunk_pixels/is_last_row/is_last_col/cut_source/risk_flags`。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
  - `LongStripChunker` 固定高度，不随宽度控制像素。
  - `TableGridChunker` 按原图几何均分，未使用 `hints.crop_box`、空白带或 line density。
  - `PageChunker` 只是 `TableGridChunker` 的空子类，普通页没有“低于阈值整页优先”的独立策略。
  - manifest 只写基础字段，无法审计切线来源和像素预算。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - `_chunk()` 直接读取扁平 `config.chunk` 字典，无法表达 long/table/normal 分层预算。
  - dry-run QC 只写 chunk 数，无法验收 `over_safe/over_hard`。

## 3. 文件结构与职责

### 3.1 生产代码

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
  - 定义 `ChunkConfig`、`LongChunkConfig`、`TableChunkConfig`、`NormalChunkConfig`。
  - 支持新嵌套配置和旧扁平配置兼容读取。
  - 固化 `hard_max_pixels/min_pixels/crop_margin_px` 的默认值。

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_geometry.py`
  - 纯函数：`box_pixels()`、`expand_box()`、`nearest_band_center()`、`traceable_chunk_name()`、`overlap_dict()`。
  - 只处理坐标与像素预算，不依赖 Pipeline 或 API。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
  - 扩展 `Chunk` 的可审计字段，保持默认值以兼容现有测试构造器。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
  - `RunConfig.chunk` 支持 `ChunkConfig | Mapping[str, Any]`，并在 `__post_init__()` 归一化为 `ChunkConfig`。
  - `snapshot()` 输出可 YAML 序列化的配置字典，继续隐藏 `api_key`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
  - `LongStripChunker` 使用内容区、动态高度、空白带切线和像素风险标记。
  - `TableGridChunker` 使用内容区、分类型像素预算、overlap 后安全校验、空白带切线。
  - `PageChunker` 实现 normal 页整页优先，超过阈值后走轻量网格。
  - manifest 增加顶层 `content_box/chunk_policy` 和 chunk 级审计字段。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - `_chunk()` 使用 `ChunkConfig` 的分类型配置实例化 chunker。
  - `_write_dry_run_qc()` 写入 `max_chunk_pixels/over_safe_chunks/over_hard_chunks/chunk_policy` 等 dry-run 指标。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
  - 改为分层 chunk 配置。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/long_strip.yaml`
  - 只覆盖 long 相关配置，保持同一 schema。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_grid.yaml`
  - 只覆盖 table 相关配置，保持同一 schema。

### 3.2 测试文件

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py`

## 4. 接口契约

### 4.1 配置契约

新配置 schema：

```yaml
chunk:
  hard_max_pixels: 16777216
  safe_max_pixels: 12000000
  min_pixels: 4096
  crop_margin_px: 24

  long:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    max_window_height: 4000
    min_window_height: 1800
    vertical_overlap: 320
    blank_band_search_px: 360

  table:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    full_page_max_pixels: 8000000
    horizontal_overlap: 160
    vertical_overlap: 220
    cut_search_px: 260

  normal:
    full_page_max_pixels: 12000000
    target_pixels: 8000000
```

兼容规则：

- 旧 `chunk.max_chunk_pixels` 映射到 `table.target_pixels`。
- 旧 `chunk.table_full_page_max_pixels` 映射到 `table.full_page_max_pixels`。
- 旧 `chunk.long_window_height` 映射到 `long.max_window_height`。
- 旧 `chunk.long_vertical_overlap` 映射到 `long.vertical_overlap`。
- 旧 `chunk.table_horizontal_overlap/table_vertical_overlap` 映射到 table overlap。

关键断言：

```python
cfg = ChunkConfig.from_mapping({"max_chunk_pixels": 4_000_000})
assert cfg.table.target_pixels == 4_000_000
assert cfg.hard_max_pixels == 16_777_216
```

### 4.2 `RunConfig` 兼容契约

`RunConfig` 必须允许现有测试继续传入旧扁平 dict，同时 `load_config()` 返回 typed config。关键 diff：

```diff
-    chunk: dict[str, int]
+    chunk: ChunkConfig | Mapping[str, Any]
+
+    def __post_init__(self) -> None:
+        if not isinstance(self.chunk, ChunkConfig):
+            object.__setattr__(self, "chunk", ChunkConfig.from_mapping(self.chunk))
```

`snapshot()` 必须输出普通 dict，避免 `yaml.safe_dump()` 遇到自定义对象：

```python
payload["chunk"] = self.chunk.to_dict()
```

验收要求：

- `load_config(args).chunk` 是 `ChunkConfig`。
- 直接用旧扁平 chunk 配置构造 `RunConfig` 后，`config.chunk.table.target_pixels == 12_000_000`。
- `tests/test_cli_sampling.py`、`tests/test_submission.py`、`tests/test_pipeline_quality_blocking.py` 中的旧 fixture 不需要一次性重写也能通过。

### 4.3 `Chunk` 契约

在现有 `Chunk` 后追加默认字段，避免影响 `tests/test_finix_api.py` 等直接构造 `Chunk` 的测试：

```diff
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
+    chunk_pixels: int = 0
+    is_last_row: bool = False
+    is_last_col: bool = False
+    cut_source: str = "unknown"
+    risk_flags: tuple[str, ...] = ()
```

字段含义：

- `chunk_pixels`: `(x1 - x0) * (y1 - y0)`，按最终 bbox 计算，包含 overlap。
- `is_last_row/is_last_col`: 最后一行/列必须为 `True`，对应的 `bottom/right` overlap 必须为 0。
- `cut_source`: 枚举字符串，首批使用 `full_page`、`dynamic_window`、`blank_band`、`grid`、`content_grid`。
- `risk_flags`: 使用 tuple 保持不可变；首批风险包括 `over_safe_pixels`、`over_hard_pixels`、`fixed_cut`、`small_tail`。

### 4.4 Manifest 契约

`{work_dir}/chunks/{stem}/manifest.json` 顶层新增：

```json
{
  "file_name": "doc.jpg",
  "width": 1500,
  "height": 80299,
  "doc_type": "long_strip",
  "content_box": [0, 12, 1500, 80270],
  "chunk_policy": "long_dynamic_v1",
  "chunks": []
}
```

chunk 条目必须包含：

```json
{
  "chunk_id": "string",
  "image_path": "string",
  "bbox": [0, 0, 1500, 4000],
  "row": 0,
  "col": 0,
  "chunk_pixels": 6000000,
  "overlap": {"top": 0, "bottom": 320, "left": 0, "right": 0},
  "is_last_row": false,
  "is_last_col": true,
  "cut_source": "blank_band",
  "risk_flags": []
}
```

切片文件名：

```text
{原图stem}__r{row}_c{col}__x{x0}_y{y0}_w{w}_h{h}.jpg
```

`chunk_id` 仍由 `sha1(file_name + bbox + image_sha1)[:16]` 生成，保证 cache 追踪不依赖文件名格式。

### 4.5 Chunker 构造器兼容契约

三类 chunker 都必须支持 `config=ChunkConfig`，并保留旧参数入口，避免一次性修改所有旧测试：

```python
LongStripChunker(chunks_dir, config=cfg)
TableGridChunker(chunks_dir, config=cfg)
PageChunker(chunks_dir, config=cfg)
```

旧入口继续可用：

```python
LongStripChunker(chunks_dir, window_height=4000, overlap=320)
TableGridChunker(chunks_dir, max_chunk_pixels=12_000_000, full_page_max_pixels=16_000_000)
```

优先级规则：

- 若传入 `config`，使用 `config.long/table/normal`。
- 若未传入 `config`，使用旧参数构造一个等价的临时 `ChunkConfig`。
- `Pipeline._chunk()` 只使用 `config=self.config.chunk`。

### 4.6 Long 切分契约

输入：

- `ImageProfile`
- `LayoutHints`
- `LongChunkConfig`
- 全局 `hard_max_pixels/min_pixels/crop_margin_px`

规则：

- 先把 `hints.crop_box` 扩展为 `content_box = expand_box(hints.crop_box, crop_margin_px, profile.width, profile.height)`。
- long 默认全内容宽度纵向切，不横向网格切。
- 动态高度按内容宽度计算，最终 bbox 不应超过 `long.safe_max_pixels`；若超过，必须带 `over_safe_pixels` 风险。
- 目标切线在 `±blank_band_search_px` 内找水平空白带，找到则 `cut_source="blank_band"`；找不到则 `cut_source="dynamic_window"` 并在非尾块标记 `fixed_cut`。

关键公式：

```python
target_h = max(1, cfg.long.target_pixels // content_width)
safe_h = max(1, cfg.long.safe_max_pixels // content_width)
window_h = min(cfg.long.max_window_height, max(cfg.long.min_window_height, target_h), safe_h)
```

### 4.7 Table 切分契约

规则：

- `content_pixels <= table.full_page_max_pixels` 时输出一个 `content_box` 整页 chunk，`cut_source="full_page"`。
- 超过整页阈值时按 `table.target_pixels` 估算行列数。
- 行列数估算必须把 overlap 后的最终 bbox 纳入预算，验收以 `chunk.chunk_pixels <= table.safe_max_pixels` 为准。
- 横切线优先使用 `hints.horizontal_blank_bands`，竖切线优先使用 `hints.vertical_blank_bands`，搜索半径为 `table.cut_search_px`。
- 找不到空白带时保留网格切线，并给相关 chunk 增加 `fixed_cut` 风险。

`table_line_density` 的使用：

- `table_line_density < 0.08` 只降低结构风险判断，不自动抬高 `table.full_page_max_pixels`。
- 只有 `content_pixels <= table.full_page_max_pixels` 时才输出整页 chunk；如后续实验要放宽整页阈值，只改配置，不在代码中按文件名或数据集写分支。
- 高线密度表格不因低于 hard max 自动整页，优先按 table 网格切分保护结构。

### 4.8 Normal 页契约

规则：

- `content_pixels <= normal.full_page_max_pixels` 时输出一个 `content_box` 整页 chunk。
- 超过阈值时复用轻量网格切分，目标像素为 `normal.target_pixels`，overlap 默认使用 table 的 overlap 或更小值。
- `PageChunker` 不再是空子类，必须声明 `chunk_policy="normal_page_v1"`。

### 4.9 Dry-run QC 契约

dry-run 仍不调用 API，但每个文件 QC 应写入：

```json
{
  "metrics": {
    "doc_type": "table_page",
    "chunks": 4,
    "dry_run": true,
    "chunk_policy": "table_grid_v2",
    "max_chunk_pixels": 7920000,
    "over_safe_chunks": 0,
    "over_hard_chunks": 0
  }
}
```

正式 API 流程不因这些字段改变；它们用于数据级验收和调参。

## 5. 实施任务

### Task 1: ChunkConfig 分层配置与兼容读取

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/long_strip.yaml`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_grid.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`
- Verify unchanged compatibility: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py`
- Verify unchanged compatibility: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py`
- Verify unchanged compatibility: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 写配置兼容失败测试**

在 `tests/test_chunk_config.py` 新增测试，覆盖新嵌套 schema 与旧扁平 schema。关键断言：

```python
cfg = ChunkConfig.from_mapping({"max_chunk_pixels": 4_000_000, "long_window_height": 4000})
assert cfg.table.target_pixels == 4_000_000
assert cfg.long.max_window_height == 4000
assert cfg.hard_max_pixels == 16_777_216

nested = ChunkConfig.from_mapping({"table": {"target_pixels": 6_000_000}})
assert nested.table.target_pixels == 6_000_000
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py -q
```

Expected: FAIL，提示 `ChunkConfig` 不存在。

- [ ] **Step 2: 实现 `chunk_config.py` 最小结构**

创建 dataclass，并提供 `from_mapping()`、`to_dict()`。关键字段与接口：

```text
ChunkConfig.hard_max_pixels: int
ChunkConfig.safe_max_pixels: int
ChunkConfig.min_pixels: int
ChunkConfig.crop_margin_px: int
ChunkConfig.long: LongChunkConfig
ChunkConfig.table: TableChunkConfig
ChunkConfig.normal: NormalChunkConfig
ChunkConfig.from_mapping(raw: Mapping[str, Any]) -> ChunkConfig
ChunkConfig.to_dict() -> dict[str, Any]
```

- [ ] **Step 3: 修改 `RunConfig` 使用 `ChunkConfig`**

关键 diff：

```diff
-from typing import Any
+from typing import Any, Mapping
@@
-    chunk: dict[str, int]
+    chunk: ChunkConfig | Mapping[str, Any]
+
+    def __post_init__(self) -> None:
+        if not isinstance(self.chunk, ChunkConfig):
+            object.__setattr__(self, "chunk", ChunkConfig.from_mapping(self.chunk))
@@
-        chunk=dict(raw.get("chunk", {})),
+        chunk=ChunkConfig.from_mapping(raw.get("chunk", {})),
```

`snapshot()` 中对 `paths` 和 `api_key` 的处理保持不变，`chunk` 使用 `config.chunk.to_dict()`。

- [ ] **Step 4: 更新 YAML 配置**

`configs/default.yaml` 改为第 4.1 节 schema。`configs/long_strip.yaml`、`configs/table_grid.yaml` 也使用同一嵌套结构，只覆盖对应子树。

同步修改 `tests/test_chunkers.py::test_default_table_config_splits_15m_pixel_pages_for_api_stability` 的断言：

```python
chunk = config["chunk"]
assert chunk["hard_max_pixels"] == 16_777_216
assert chunk["table"]["full_page_max_pixels"] <= 8_000_000
assert chunk["table"]["target_pixels"] == 6_000_000
```

- [ ] **Step 5: 跑配置测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_default_table_config_splits_15m_pixel_pages_for_api_stability /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py::test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py::test_pipeline_reruns_once_after_retryable_quality_failure -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/long_strip.yaml /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/table_grid.yaml /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: add typed chunk configuration"
```

### Task 2: Chunk 几何工具与 manifest 字段

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_geometry.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写几何工具失败测试**

关键断言：

```python
assert box_pixels((10, 20, 30, 50)) == 800
assert expand_box((10, 20, 30, 50), margin=5, width=100, height=100) == (5, 15, 35, 55)
assert nearest_band_center(100, [(80, 90), (105, 115)], search_px=20) == (110, "blank_band")
assert traceable_chunk_name("doc", 1, 2, (10, 20, 110, 220)) == "doc__r1_c2__x10_y20_w100_h200.jpg"
assert overlap_dict(row=0, col=1, rows=2, cols=2, horizontal=160, vertical=220) == {
    "left": 160,
    "right": 0,
    "top": 0,
    "bottom": 220,
}
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py -q
```

Expected: FAIL，提示工具函数不存在。

- [ ] **Step 2: 扩展 `Chunk` 字段**

按第 4.3 节小 diff 追加默认字段。旧测试中直接构造 `Chunk` 的写法无需改动。

- [ ] **Step 3: 实现 `chunk_geometry.py`**

关键函数签名：

```text
box_pixels(box: tuple[int, int, int, int]) -> int
expand_box(box: tuple[int, int, int, int], margin: int, width: int, height: int) -> tuple[int, int, int, int]
nearest_band_center(target: int, bands: list[tuple[int, int]], search_px: int) -> tuple[int, str]
traceable_chunk_name(stem: str, row: int, col: int, bbox: tuple[int, int, int, int]) -> str
overlap_dict(row: int, col: int, rows: int, cols: int, horizontal: int, vertical: int) -> dict[str, int]
```

- [ ] **Step 4: 修改 manifest 写入函数**

`_write_manifest()` 接受 `content_box` 和 `chunk_policy`。关键结构：

```python
payload = {
    "file_name": profile.file_name,
    "width": profile.width,
    "height": profile.height,
    "doc_type": profile.doc_type,
    "content_box": content_box,
    "chunk_policy": chunk_policy,
    "chunks": chunk_payloads,
}
```

所有调用点都必须传入这两个字段：long 使用 `long_dynamic_v1`，table 使用 `table_grid_v2`，normal 使用 `normal_page_v1`。`TableGridChunker._materialize()` 需要接收并透传 `content_box/chunk_policy`，不能只修 long 分支。

- [ ] **Step 5: 写 manifest 字段测试**

在 `tests/test_chunkers.py` 增加断言：

```python
manifest = json.loads((tmp_path / "chunks" / "long" / "manifest.json").read_text())
assert manifest["content_box"] == [0, 0, 1500, 10000]
assert manifest["chunk_policy"] == "long_dynamic_v1"
assert {"chunk_pixels", "is_last_row", "is_last_col", "cut_source", "risk_flags"} <= set(manifest["chunks"][0])
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_long_strip_chunks_cover_height_and_have_stable_ids -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunk_geometry.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: enrich chunk manifest metadata"
```

### Task 3: LongStripChunker 动态高度、内容区与空白带切线

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写动态高度失败测试**

构造 `5000 x 12000` 宽长图，设置 `long.safe_max_pixels=8_000_000`。关键断言：

```python
assert all(c.chunk_pixels <= 8_000_000 for c in chunks)
assert max(c.bbox[3] - c.bbox[1] for c in chunks) <= 1600
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_long_dynamic_height_respects_safe_max_pixels -q
```

Expected: FAIL，当前固定 4000 高会超过 8M。

- [ ] **Step 2: 写内容区裁剪失败测试**

构造 `1000 x 1000` 图，传入 `hints.crop_box=(100, 200, 900, 800)`、`crop_margin_px=24`。关键断言：

```python
assert manifest["content_box"] == [76, 176, 924, 824]
assert chunks[0].bbox[0] == 76
assert chunks[0].bbox[2] == 924
```

Expected: FAIL，当前从整图 `(0, 0, width, height)` 切。

- [ ] **Step 3: 写空白带切线失败测试**

构造候选切线附近的水平空白带，例如 `horizontal_blank_bands=[(3150, 3230)]`，设置 `blank_band_search_px=360`。关键断言：

```python
assert chunks[0].bbox[3] == 3190
assert chunks[0].cut_source == "blank_band"
```

Expected: FAIL，当前搜索范围由 overlap 间接控制，且未记录 `cut_source`。

- [ ] **Step 4: 修改 `LongStripChunker` 初始化契约**

保留旧参数兼容，新增 `chunk_config` 推荐入口：

```python
LongStripChunker(chunks_dir: Path, config: ChunkConfig | None = None, window_height: int = 4000, overlap: int = 320)
```

`Pipeline._chunk()` 使用 `config=self.config.chunk`，测试中可继续用旧参数或显式传 `ChunkConfig`。

- [ ] **Step 5: 实现 long 切分策略**

实现第 4.6 节契约，注意：

- bbox 使用原图坐标。
- `overlap` 字典包含 `left/right/top/bottom` 四个键。
- 最后一块 `is_last_row=True`，`overlap["bottom"] == 0`。
- `chunk_pixels` 按最终 bbox 写入。
- `risk_flags` 中不能出现重复字符串。

- [ ] **Step 6: 跑 long 相关测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py -q
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: optimize long strip chunking"
```

### Task 4: TableGridChunker overlap 后像素预算与空白带切线

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写 table 像素预算失败测试**

构造 `6000 x 4200` 表格图，设置 `table.target_pixels=6_000_000`、`table.safe_max_pixels=6_000_000`、overlap 为 `160/220`。这个用例专门验证 overlap 后像素仍受预算约束，旧算法只按基础网格估算，容易在加入 overlap 后超过 6M。关键断言：

```python
cfg = ChunkConfig.from_mapping({
    "table": {
        "target_pixels": 6_000_000,
        "safe_max_pixels": 6_000_000,
        "full_page_max_pixels": 1_000_000,
        "horizontal_overlap": 160,
        "vertical_overlap": 220,
    }
})
chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)
assert len(chunks) > 1
assert all(c.chunk_pixels <= 6_000_000 for c in chunks)
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_table_overlap_included_in_pixel_budget -q
```

Expected: FAIL，当前 `TableGridChunker` 不接受 `config=`，且按基础网格估算时不会把 overlap 后像素作为预算闭环。

- [ ] **Step 2: 写最后行/列 overlap 元数据失败测试**

关键断言：

```python
for chunk in chunks:
    if chunk.is_last_col:
        assert chunk.overlap["right"] == 0
    if chunk.is_last_row:
        assert chunk.overlap["bottom"] == 0
```

Expected: FAIL，当前最后行/列仍写固定 `right/bottom`。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_last_row_col_overlap_metadata -q
```

Expected: FAIL。

- [ ] **Step 3: 写 table 空白带切线失败测试**

传入 `horizontal_blank_bands` 和 `vertical_blank_bands`，让候选网格线附近有空白带。关键断言：

```python
content_box = (100, 100, 5900, 4100)
hints = LayoutHints(content_box, [(1980, 2060)], [(2980, 3060)], 0.5, 1)
chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)
assert any(c.cut_source == "blank_band" for c in chunks)
assert all(c.bbox[0] >= content_box[0] and c.bbox[2] <= content_box[2] for c in chunks)
```

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py::test_table_cut_adjusts_to_blank_band -q
```

Expected: FAIL。

- [ ] **Step 4: 实现 table grid shape 估算**

新增私有函数，名称固定便于测试或局部调用：

```text
_estimate_grid_shape(width: int, height: int, target_pixels: int, safe_max_pixels: int, hard_max_pixels: int, overlap_x: int, overlap_y: int) -> tuple[int, int]
```

验收规则：

- 对每个最终 bbox 计算 `chunk_pixels`。
- 若任一 chunk 超过 safe max，则增加 rows 或 cols 后重新生成。
- 若极端尺寸在合理 rows/cols 下仍超过 hard max，必须继续拆分直到不超过 hard max。

- [ ] **Step 5: 实现 cut adjustment**

只使用当前 `LayoutHints` 已有空白带；低密度投影扫描不在本任务新增。切线调整后仍需保持：

- `x_cuts[0] == content_box[0]`
- `x_cuts[-1] == content_box[2]`
- `y_cuts[0] == content_box[1]`
- `y_cuts[-1] == content_box[3]`
- cuts 单调递增，不能产生空 bbox。

- [ ] **Step 6: 跑 table 相关测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py -q
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: optimize table grid chunking"
```

### Task 5: PageChunker normal 页整页优先

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py`

- [ ] **Step 1: 写 normal 整页优先失败测试**

构造 `3000 x 3000` 普通页，`content_pixels=9M <= normal.full_page_max_pixels=12M`。关键断言：

```python
chunks = PageChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)
assert len(chunks) == 1
assert chunks[0].cut_source == "full_page"
assert chunks[0].bbox == (0, 0, 3000, 3000)
```

Expected: FAIL，当前 `PageChunker` 继承 table 默认 `table_full_page_max_pixels=8M` 时会切网格。

- [ ] **Step 2: 实现 `PageChunker`**

实现 normal 契约：

- 小于等于 `normal.full_page_max_pixels` 直接整页。
- 超过阈值使用 `normal.target_pixels` 轻量网格。
- `chunk_policy="normal_page_v1"`。

- [ ] **Step 3: 修改 `Pipeline._chunk()`**

`profile.doc_type == "normal_page"` 时实例化 `PageChunker(self.config.paths.chunks_dir, config=self.config.chunk)`。

- [ ] **Step 4: 跑测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/chunkers.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py
git commit -m "feat: prefer full page chunks for normal pages"
```

### Task 6: dry-run 切片统计与数据级验收入口

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py`

- [ ] **Step 1: 写 dry-run QC 指标失败测试**

在 `tests/test_submission.py::test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv` 中断言单文件 QC 包含切片预算指标。该测试已创建 `one.png`，所以 QC 路径必须使用 `one.json`。关键断言：

```python
qc = json.loads((config.paths.qc_dir / "one.json").read_text(encoding="utf-8"))
metrics = qc["metrics"]
assert metrics["dry_run"] is True
assert metrics["chunks"] >= 1
assert "max_chunk_pixels" in metrics
assert metrics["over_hard_chunks"] == 0
```

Expected: FAIL，当前 `_write_dry_run_qc()` 只写 `doc_type/chunks/dry_run`。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py::test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv -q
```

Expected: FAIL。

- [ ] **Step 2: 实现 dry-run 统计**

`Pipeline._write_dry_run_qc(profile, chunks)` 改为接收 chunk 列表，统计：

- `chunk_policy`: 按 `profile.doc_type` 固定映射为 `long_dynamic_v1`、`table_grid_v2` 或 `normal_page_v1`；不要新增 `Chunk.chunk_policy` 字段。
- `max_chunk_pixels`: `max(chunk.chunk_pixels)`。
- `over_safe_chunks`: `sum("over_safe_pixels" in chunk.risk_flags for chunk in chunks)`。
- `over_hard_chunks`: `sum(chunk.chunk_pixels > self.config.chunk.hard_max_pixels for chunk in chunks)`。

- [ ] **Step 3: 修改调用点**

关键 diff：

```diff
- self._write_dry_run_qc(profile, chunks_count=len(chunks))
+ self._write_dry_run_qc(profile, chunks)
```

- [ ] **Step 4: 跑 dry-run 测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py::test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Expected: PASS。

- [ ] **Step 5: 本地数据级 dry-run 验收命令**

该命令只读取 `data/`，不修改原始数据，不调用 API：

```bash
python -m finix_restore.cli \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --output_csv /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_dry_run/submission.csv \
  --work_dir /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_dry_run \
  --config /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml \
  --dry_run \
  --limit_per_dir 5
```

Expected:

- 命令退出码为 0。
- `outputs/chunk_dry_run/chunks/*/manifest.json` 存在。
- `outputs/chunk_dry_run/qc/summary.json` 存在。
- 所有 manifest chunk 的 `chunk_pixels <= 16777216`。

- [ ] **Step 6: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py
git commit -m "feat: report chunk budgets in dry run"
```

### Task 7: 全量回归与提交格式保护

**Files:**

- No production file required unless tests expose a regression.

- [ ] **Step 1: 运行核心切分测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行相关链路测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行全量单测**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests -q
```

Expected: PASS。

- [ ] **Step 4: 运行 diff 空白检查**

Run:

```bash
git diff --check
```

Expected: no output。

- [ ] **Step 5: 校验 dry-run 产物不进入提交**

Run:

```bash
git status --short
```

Expected:

- 只显示源码、配置、测试和计划相关文件。
- 不显示 `outputs/` 下运行产物。
- 不显示 `.env`。

## 6. 数据级验收标准

### 6.1 单元测试验收

必须通过：

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_geometry.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunkers.py -q
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py -q
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests -q
```

### 6.2 dry-run 验收

对训练集 long/table 各取 5 张：

- 所有切片 `chunk_pixels <= config.chunk.hard_max_pixels`。
- 常规切片 `chunk_pixels <= 对应类型 safe_max_pixels`；若超过，manifest 必须有 `over_safe_pixels`。
- long chunk 的 `bbox` 横向落在 `content_box` 范围内，纵向覆盖 `content_box`，没有空洞。
- table chunk 的 `is_last_col` 对应 `overlap["right"] == 0`，`is_last_row` 对应 `overlap["bottom"] == 0`。
- manifest 包含 `content_box/chunk_policy/chunk_pixels/cut_source/risk_flags`。

### 6.3 API 小样本验收

只有在 dry-run 和单测通过后执行。示例命令不应打印密钥：

```bash
python -m finix_restore.cli \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --output_csv /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_api_smoke/submission.csv \
  --work_dir /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_api_smoke \
  --config /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml \
  --limit_per_dir 2
```

验收：

- `outputs/chunk_api_smoke/logs/run.jsonl` 不包含 `FINIX_API_KEY`、真实 `apiKey` 或 `.env` 原文。
- `submission.csv` 可被 pandas 读取。
- 列名严格为 `file_name,ground_truth`。
- 行数为 4。
- 无重复 `file_name`。

校验命令：

```bash
python - <<'PY'
import pandas as pd
path = "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_api_smoke/submission.csv"
df = pd.read_csv(path)
assert list(df.columns) == ["file_name", "ground_truth"]
assert len(df) == 4
assert not df["file_name"].duplicated().any()
print("submission smoke ok")
PY
```

## 7. 风险与回滚点

- 配置 schema 改动会影响测试 fixture 中的旧扁平 `RunConfig` 写法。缓解：`ChunkConfig.from_mapping()` 支持旧扁平 dict；测试 fixture 可逐步改为显式 typed config。
- 切片文件名从 `{chunk_id}.jpg` 改为可追溯名会改变 API `fileName`，但 `chunk_id` 和 cache meta 仍绑定 bbox/hash；旧 cache 不会被错误复用。
- `crop_box` 若被 LayoutSentry 误判过窄，可能裁掉边缘内容。缓解：默认 `crop_margin_px=24`，且测试覆盖 crop margin；如验收发现风险，可在配置调大 margin，而不改代码。
- 空白带切线可能造成极小残片。缓解：小残片合并或记录 `small_tail`，并在 manifest 中暴露。
- 6M 默认目标比 FinixDoc-VL 1M-4M 推荐工作点更激进。缓解：使用 8M safe max 和 16.78M hard max；如 API 小样本超时，先把 `long.target_pixels/table.target_pixels` 降到 4M。

## 8. 自查结果

Spec coverage:

- FinixDoc-VL hard max、min pixels、推荐工作点：Task 1、Task 3、Task 4、验收 6.2 覆盖。
- long/table/normal 分类型策略：Task 3、Task 4、Task 5 覆盖。
- `LayoutSentry.crop_box` 和空白带接入：Task 3、Task 4 覆盖。
- manifest 可追溯字段：Task 2 覆盖。
- dry-run 与提交 CSV 验收：Task 6、Task 7、验收 6.3 覆盖。
- 不调用其他大模型、不改 data、不泄露密钥：1 节强约束与 6.3 验收覆盖。

Placeholder scan:

- 本计划没有遗留占位项或无约束的“稍后实现”表述。
- 代码块均为接口、小 diff、关键断言或命令，不包含大段完整实现。

Type consistency:

- `ChunkConfig`、`LongChunkConfig`、`TableChunkConfig`、`NormalChunkConfig` 命名在任务与接口契约中一致。
- `chunk_pixels/is_last_row/is_last_col/cut_source/risk_flags` 在模型、manifest、测试和验收中一致。
- `chunk_policy` 的首批值为 `long_dynamic_v1`、`table_grid_v2`、`normal_page_v1`。
