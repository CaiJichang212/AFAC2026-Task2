# Task2 复杂金融文档还原挑战 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建设一套可审计、可断点续跑、可在 3 小时内生成 A/B 榜 `submission.csv` 的端到端复杂金融文档图片到 Markdown 还原系统。

**Architecture:** 本地只做轻量图像画像、切块、规则后处理、质量门禁和 CSV 生成；唯一视觉语言模型接口是 FinixDoc-VL API。整体流程为 `ImageProfiler -> LayoutSentry -> Chunker -> FinixApiClient -> MarkdownNormalizer -> ReadingOrderResolver -> DedupMerger -> TableMerger -> QualityGate -> SubmissionWriter`，所有中间产物落盘以支持复现、审计和失败重跑。

**Tech Stack:** Python 3.10+、Pillow、OpenCV headless、numpy、pandas、requests/httpx、python-dotenv、PyYAML、beautifulsoup4/lxml、pytest、ruff。

---

## 1. 目标与强约束

### 1.1 竞赛目标

- 输入：`data/AFAC A榜评测数据集/*/images` 或后续 B 榜图片目录。
- 输出：仅含 `file_name,ground_truth` 两列的 UTF-8 CSV，字段内换行由 CSV writer 正确转义。
- 评分关注：文本编辑距离、表格 TEDS、阅读顺序编辑距离。
- 工程目标：100 张测试图片在 3 小时内稳定产出，失败可断点续跑，输出可追溯到切块、API 原始响应和后处理日志。

### 1.2 合规红线

- 最终工程只允许调用 FinixDoc-VL 作为大模型/视觉语言模型接口。
- 不接入 OpenAI、通义、Claude、本地大模型等任何其他推理接口。
- 不读取、提交或打印 `.env` 中真实 `apiKey`。
- 不按 A/B 榜测试文件名硬编码结果、切块策略或固定拼接内容。
- 本地辅助算法必须是 CPU 可运行规则/统计方法；如使用轻量模型，参数量必须小于 10M，并在复现文档注明来源和大小。

---

## 2. 目标仓库结构

从当前仓库根目录 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2` 新增以下工程文件：

```text
.
├── main.py
├── run.sh
├── requirements.txt
├── .env.example
├── configs/
│   ├── default.yaml
│   ├── long_strip.yaml
│   └── table_grid.yaml
├── finix_restore/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── paths.py
│   ├── profiler.py
│   ├── layout_sentry.py
│   ├── chunkers.py
│   ├── finix_api.py
│   ├── normalizer.py
│   ├── reading_order.py
│   ├── dedup.py
│   ├── table_merger.py
│   ├── quality_gate.py
│   ├── retry_planner.py
│   ├── submission.py
│   └── pipeline.py
├── tests/
│   ├── fixtures/
│   │   ├── mini_long.jpg
│   │   ├── mini_table.html
│   │   └── chunks_manifest.json
│   ├── test_config.py
│   ├── test_profiler.py
│   ├── test_chunkers.py
│   ├── test_dedup.py
│   ├── test_table_merger.py
│   ├── test_quality_gate.py
│   └── test_submission.py
└── docs/
    ├── reproduce.md
    └── prompt_specs.md
```

运行期产物统一写入 `outputs/`，不提交真实结果缓存：

```text
outputs/
├── profiles/{stem}.json
├── chunks/{stem}/{chunk_id}.jpg
├── chunks/{stem}/manifest.json
├── api_raw/{stem}/{chunk_id}.md
├── normalized/{stem}/{chunk_id}.md
├── merged/{stem}.md
├── qc/{stem}.json
├── logs/run.jsonl
├── metrics/local_eval.json
└── submission.csv
```

---

## 3. 模块职责与文件契约

### 3.1 `finix_restore/models.py`

定义跨模块传递的数据结构，所有模块只通过这些结构交换状态。

关键契约：

```python
@dataclass(frozen=True)
class ImageProfile:
    file_name: str
    path: Path
    width: int
    height: int
    pixels: int
    aspect: float
    doc_type: Literal["long_strip", "table_page", "normal_page", "unknown"]
    risk_level: Literal["low", "medium", "high", "extreme"]

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
```

验收点：

- `Chunk.bbox` 使用原图坐标 `(x0, y0, x1, y1)`，右下角为开区间。
- `chunk_id` 稳定可复现，建议为 `sha1(file_name + bbox + image_sha1)[:16]`。
- 模块之间不得传递裸字典作为主要领域对象。

### 3.2 `finix_restore/config.py`

负责读取 YAML、`.env` 和命令行覆盖参数，统一生成 `RunConfig`。

环境变量契约：

```text
FINIX_API_KEY=...
FINIX_USER_IDS=finixA1001,finixB2002,finixC3003
FINIX_API_URL=https://finixdocapi.alipay.com/api/finix_doc/call_with_file
```

关键规则：

- 真实 `.env` 不提交；`.env.example` 只列变量名。
- `FINIX_USER_IDS` 为英文逗号分隔列表，API 调度轮询使用。
- 初始并发按 `min(config.api.concurrency, len(user_ids) * config.api.per_user_concurrency)` 控制。
- 配置快照写入 `outputs/logs/config_snapshot.yaml`，其中 `api_key` 必须脱敏为 `***`。

### 3.3 `finix_restore/profiler.py`

读取图片尺寸、像素、长宽比、文件大小，并判断 `doc_type` 与 `risk_level`。

分类初值：

```python
if aspect >= 10 or height >= 30_000:
    doc_type = "long_strip"
elif pixels >= 15_000_000 and 1.25 <= max(width, height) / min(width, height) <= 1.55:
    doc_type = "table_page"
else:
    doc_type = "normal_page"
```

验收点：

- PIL 对极大图片可能触发 `DecompressionBombWarning`，需要显式允许但记录风险。
- profile JSON 与 PIL 读取尺寸完全一致。
- 不根据文件名区分长条/表格。

### 3.4 `finix_restore/layout_sentry.py`

在缩略图或灰度低分辨率图上做投影、线条密度、白边检测。

输出契约：

```python
@dataclass(frozen=True)
class LayoutHints:
    crop_box: tuple[int, int, int, int]
    horizontal_blank_bands: list[tuple[int, int]]
    vertical_blank_bands: list[tuple[int, int]]
    table_line_density: float
    column_count: int
```

验收点：

- 只输出切块提示，不生成最终文本。
- 所有缩略图坐标必须映射回原图坐标。
- 检测失败时返回空提示，由 chunker 使用固定窗口降级。

### 3.5 `finix_restore/chunkers.py`

按文档类型生成切块和 `manifest.json`。

策略契约：

- `LongStripChunker`：保持原图宽度，纵向滑窗，默认窗口高度 4000px，纵向 overlap 320px，优先把 `y1` 移到附近空白带。
- `TableGridChunker`：当整图像素低于 `table.full_page_max_pixels` 时先保存整图切块；否则按二维网格，默认单块不超过 12M 像素，横向 overlap 160px，纵向 overlap 220px。
- `PageChunker`：普通图小于阈值时整页，否则按最大像素拆分。

覆盖校验：

```python
def assert_cover_height(chunks, width, height):
    covered = [False] * height
    for c in chunks:
        x0, y0, x1, y1 = c.bbox
        assert 0 <= x0 < x1 <= width
        assert 0 <= y0 < y1 <= height
        for y in range(y0, y1):
            covered[y] = True
    assert all(covered)
```

文档中只保留上面这种约束片段；完整实现进入代码。

### 3.6 `finix_restore/finix_api.py`

封装 FinixDoc-VL API 上传、并发、重试、缓存和日志。

请求契约：

```text
POST https://finixdocapi.alipay.com/api/finix_doc/call_with_file
Content-Type: multipart/form-data
fields:
  userId=<从 FINIX_USER_IDS 轮询选择>
  apiKey=<FINIX_API_KEY>
  fileName=<chunk 图片文件名>
  file=@<chunk 图片路径>
response:
  text/markdown 或纯文本 Markdown 字符串
```

缓存契约：

- 缓存命中条件：`chunk_id + image_sha1 + api_url` 完全一致。
- 原始响应写入 `outputs/api_raw/{stem}/{chunk_id}.md`。
- API 请求日志写入 `outputs/logs/run.jsonl`，字段包括 `event=api_call`、`file_name`、`chunk_id`、`user_id`、`status`、`elapsed_ms`、`retry_index`，不得写 `apiKey`。

重试规则：

- 空响应、HTTP 5xx、超时：指数退避重试，默认最多 3 次。
- HTTP 401/403：立即失败并提示检查 `FINIX_USER_IDS` 或 `FINIX_API_KEY`。
- 单用户连续失败时临时熔断该 `userId`，继续使用其他用户。

### 3.7 `finix_restore/normalizer.py`

做保守 Markdown 规范化。

允许：

- 统一换行为 `\n`。
- 删除行尾空格。
- 修复 `##1.1` 为 `## 1.1`。
- 删除明显 API 错误提示行，如空响应错误文本。

禁止：

- 不改写金额、百分比、条款编号、备案号。
- 不做简繁转换。
- 不把 HTML 表格强制转管道表格。
- 不语义补全文本。

### 3.8 `finix_restore/reading_order.py`

按 `Chunk` 坐标、文档类型和局部结构生成合并顺序。

排序契约：

- 长条：`y0` 主排序，`x0` 次排序。
- 表格：`row` 主排序，`col` 次排序；若整页参考切块存在，只用于质检或局部对齐，不直接与网格结果重复拼接。
- 多栏：优先识别跨栏标题，其余内容列内从上到下，再从左到右。
- 目录区：`# 条款目录` 后连续标题行标记为 `toc_block`，不参与普通重复删除。

### 3.9 `finix_restore/dedup.py`

处理 overlap 导致的重复和边界截断。

接口契约：

```python
class DedupMerger:
    def merge(self, ordered_chunks: Sequence[ChunkText]) -> MergeResult:
        ...
```

关键阈值：

- 长条 `tail/head` 窗口 1200 字。
- 表格 `tail/head` 窗口 600 字。
- 相似度阈值初始 0.88。
- 目录区、页眉页脚、表格 `<tr>` 不使用同一套段落级删除规则。

易误解点：

```diff
- if line in previous_text: drop(line)
+ if in_overlap_bbox and is_high_confidence_prefix_suffix_match: drop(line)
```

去重必须绑定 overlap 坐标和邻接关系，不能全局按文本包含删除，否则会误删目录项、标题复现和合法重复条款。

### 3.10 `finix_restore/table_merger.py`

解析和修复 HTML 表格，优先保持 API 原结构。

接口契约：

```python
class TableMerger:
    def repair(self, markdown: str) -> TableRepairResult:
        ...
```

强约束：

- 保留空 `<td></td>`，不能删除空列。
- 相邻表格块合并时只去除重复表头或重复 overlap 行。
- 标签不闭合时先规则补齐；补齐失败写入 `qc` 风险，不盲目重排单元格。
- 表格文档 GT 以 HTML 表格为主，输出不强制转管道 Markdown。

验收片段：

```python
def test_keep_empty_td():
    html = "<table><tr><td>A</td><td></td><td>C</td></tr></table>"
    repaired = TableMerger().repair(html).markdown
    assert "<td></td>" in repaired
```

### 3.11 `finix_restore/quality_gate.py`

对单图 Markdown 和最终 CSV 做阻断式质量检查。

文件级检查：

- `ground_truth.strip()` 非空。
- 输出长度不低于同类训练分布 P10 的 30%，否则标记 `too_short`。
- 重复 200 字窗口比例超过阈值时标记 `high_duplication`。
- HTML `<table>/<tr>/<td>/<th>` 标签闭合。
- 表格行列数量异常短行比例超过阈值时标记 `table_ragged_rows`。
- API 失败切块比例超过 20% 时标记 `api_failure_ratio_high`。

CSV 级检查：

- `pandas.read_csv(output_csv)` 可读。
- 列名严格等于 `["file_name", "ground_truth"]`。
- 行数等于输入图片数。
- `file_name` 集合与输入图片文件名集合一致。
- 无重复 `file_name`。

### 3.12 `finix_restore/retry_planner.py`

根据 `QualityGate` 风险决定是否重跑局部切块。

重跑策略：

- `empty_output`：缩小窗口 30%，并发降到 1，重跑该图所有切块。
- `too_short`：增加 overlap 50%，只重跑疑似断裂邻接切块。
- `html_broken`：表格图改用更细网格，保留原始响应做对比。
- `api_timeout`：降低 `max_chunk_pixels`，切换到下一个可用 `userId`。

每次重跑都写入 `outputs/qc/{stem}.json` 的 `reruns` 数组，默认最多 2 轮，避免无限循环。

### 3.13 `finix_restore/submission.py`

负责最终 CSV 写入和复验。

关键约束：

```python
df = pd.DataFrame(rows, columns=["file_name", "ground_truth"])
df.to_csv(output_csv, index=False, encoding="utf-8", lineterminator="\n")
```

写入后必须立即 `pd.read_csv(output_csv)` 回读校验。不要手写 CSV 拼接字符串。

---

## 4. 命令行与配置契约

### 4.1 CLI

入口命令：

```bash
python main.py \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --output_csv outputs/submission_long_A.csv \
  --work_dir outputs/long_A \
  --config configs/default.yaml
```

支持参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--input_dir` | 是 | 图片目录。 |
| `--output_csv` | 是 | 输出 CSV 路径。 |
| `--work_dir` | 否 | 中间产物目录，默认 `outputs/run`。 |
| `--config` | 否 | YAML 配置，默认 `configs/default.yaml`。 |
| `--limit` | 否 | 调试时只跑前 N 张，正式提交不得使用。 |
| `--resume` | 否 | 启用缓存和断点续跑，默认开启。 |
| `--force_api` | 否 | 忽略 API 缓存重跑。 |
| `--dry_run` | 否 | 只做画像、切块、manifest 和 CSV 空结构校验，不调用 API。 |

`run.sh` 契约：

```bash
#!/usr/bin/env bash
set -euo pipefail
python main.py --input_dir "$1" --output_csv "$2" --work_dir "${3:-outputs/run}" --config "${4:-configs/default.yaml}"
```

### 4.2 `configs/default.yaml`

配置内容应覆盖以下键：

```yaml
api:
  url: "${FINIX_API_URL}"
  timeout_seconds: 240
  max_retries: 3
  concurrency: 4
  per_user_concurrency: 1
chunk:
  max_chunk_pixels: 12000000
  long_window_height: 4000
  long_vertical_overlap: 320
  table_horizontal_overlap: 160
  table_vertical_overlap: 220
merge:
  dedup_window_chars_long: 1200
  dedup_window_chars_table: 600
  dedup_similarity_threshold: 0.88
quality:
  max_duplication_ratio: 0.18
  max_api_failure_ratio: 0.20
  max_reruns_per_file: 2
```

---

## 5. 实施任务

### Task 1: 工程骨架与配置加载

**Files:**

- Create: `main.py`
- Create: `run.sh`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `configs/default.yaml`
- Create: `finix_restore/__init__.py`
- Create: `finix_restore/config.py`
- Create: `finix_restore/cli.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写配置加载失败测试**

  覆盖 `.env` 缺少 `FINIX_API_KEY`、`FINIX_USER_IDS` 为空、并发大于用户数时的行为。

  Run: `pytest tests/test_config.py -q`

  Expected: 新测试在实现前失败。

- [ ] **Step 2: 实现 `RunConfig` 和 CLI 参数解析**

  最小实现只需要读 YAML、环境变量和命令行，返回统一配置对象；不得打印真实密钥。

- [ ] **Step 3: 补充 `.env.example`**

  内容只包含：

  ```text
  FINIX_API_KEY=
  FINIX_USER_IDS=
  FINIX_API_URL=https://finixdocapi.alipay.com/api/finix_doc/call_with_file
  ```

- [ ] **Step 4: 验证**

  Run: `pytest tests/test_config.py -q`

  Expected: PASS。

- [ ] **Step 5: 提交**

  ```bash
  git add main.py run.sh requirements.txt .env.example configs/default.yaml finix_restore tests/test_config.py
  git commit -m "chore: scaffold task2 restore pipeline"
  ```

### Task 2: 图片画像与文档类型分类

**Files:**

- Create: `finix_restore/models.py`
- Create: `finix_restore/profiler.py`
- Create: `tests/test_profiler.py`
- Modify: `finix_restore/pipeline.py`

- [ ] **Step 1: 写画像测试**

  覆盖长宽比大于 10 判为 `long_strip`、A 系列表格比例且大像素判为 `table_page`、极大像素判为 `extreme` 风险。

- [ ] **Step 2: 实现 `ImageProfiler`**

  只读取元信息，不把整张超大图转成 numpy 数组。

- [ ] **Step 3: 写 profile JSON**

  路径为 `outputs/profiles/{stem}.json`，字段与 `ImageProfile` 一致。

- [ ] **Step 4: 验证**

  Run: `pytest tests/test_profiler.py -q`

  Expected: PASS。

### Task 3: 轻量版面感知

**Files:**

- Create: `finix_restore/layout_sentry.py`
- Create: `tests/test_layout_sentry.py`
- Modify: `finix_restore/models.py`

- [ ] **Step 1: 写缩略图坐标映射测试**

  输入缩略图空白带坐标，断言映射回原图后不越界。

- [ ] **Step 2: 实现水平/垂直投影和白边检测**

  使用灰度缩略图即可，目标是给 chunker 提供候选切线。

- [ ] **Step 3: 实现检测失败降级**

  对低对比度或异常图返回空 `LayoutHints`，而不是抛出导致全局中断。

- [ ] **Step 4: 验证**

  Run: `pytest tests/test_layout_sentry.py -q`

  Expected: PASS。

### Task 4: 长条与表格切块

**Files:**

- Create: `finix_restore/chunkers.py`
- Create: `tests/test_chunkers.py`
- Modify: `finix_restore/models.py`
- Modify: `configs/long_strip.yaml`
- Modify: `configs/table_grid.yaml`

- [ ] **Step 1: 写 manifest 覆盖测试**

  构造 1500×10000 长条图和 6000×4200 表格图，断言切块覆盖全图、bbox 不越界、`chunk_id` 稳定。

- [ ] **Step 2: 实现 `LongStripChunker`**

  固定宽度、纵向滑窗、空白带微调、overlap 记录。

- [ ] **Step 3: 实现 `TableGridChunker`**

  按最大像素阈值计算网格，优先使用投影空白带；找不到空白带时按等距切分。

- [ ] **Step 4: 写切块图片和 `manifest.json`**

  路径必须为 `outputs/chunks/{stem}/{chunk_id}.jpg` 和 `outputs/chunks/{stem}/manifest.json`。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_chunkers.py -q`

  Expected: PASS。

### Task 5: FinixDoc-VL API 客户端、缓存与并发

**Files:**

- Create: `finix_restore/finix_api.py`
- Create: `tests/test_finix_api.py`
- Modify: `finix_restore/config.py`

- [ ] **Step 1: 写 mock API 测试**

  使用 monkeypatch 或 responses/httpx mock，断言 multipart 字段含 `userId`、`apiKey`、`fileName`、`file`，日志不含真实 `apiKey`。

- [ ] **Step 2: 实现缓存优先**

  如果 `outputs/api_raw/{stem}/{chunk_id}.md` 存在且 manifest hash 匹配，则不发请求。

- [ ] **Step 3: 实现 userId 轮询和并发限流**

  初始并发不超过 `len(FINIX_USER_IDS)`，单用户默认 1 个并发，失败后可熔断。

- [ ] **Step 4: 实现重试**

  空响应、HTTP 5xx、超时执行指数退避；401/403 直接失败。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_finix_api.py -q`

  Expected: PASS。

### Task 6: Markdown 规范化与阅读顺序

**Files:**

- Create: `finix_restore/normalizer.py`
- Create: `finix_restore/reading_order.py`
- Create: `tests/test_normalizer.py`
- Create: `tests/test_reading_order.py`

- [ ] **Step 1: 写保守规范化测试**

  覆盖 `##1.1` 修复、行尾空格删除、金额和条款号不改写。

- [ ] **Step 2: 写排序测试**

  覆盖长条按 `y0`、表格按 `row,col`、目录区不被标记为普通重复文本。

- [ ] **Step 3: 实现 `MarkdownNormalizer`**

  只做格式最小修复，不做语义纠错。

- [ ] **Step 4: 实现 `ReadingOrderResolver`**

  先坐标排序，再用标题编号和目录模式做局部标记。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_normalizer.py tests/test_reading_order.py -q`

  Expected: PASS。

### Task 7: 接缝去重与续接

**Files:**

- Create: `finix_restore/dedup.py`
- Create: `tests/test_dedup.py`

- [ ] **Step 1: 写 overlap 去重测试**

  构造相邻切块末尾/开头重复 100 字，断言合并后只保留一次。

- [ ] **Step 2: 写目录保护测试**

  构造目录标题和正文标题重复，断言目录项不被删除。

- [ ] **Step 3: 实现 prefix/suffix 匹配**

  用 `difflib.SequenceMatcher` 或轻量 n-gram 相似度即可，必须受邻接切块和 overlap 约束。

- [ ] **Step 4: 实现段落续接**

  前块末尾未闭合括号、句子或 HTML 标签时，合并时避免额外插入空段。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_dedup.py -q`

  Expected: PASS。

### Task 8: HTML 表格修复与跨块合并

**Files:**

- Create: `finix_restore/table_merger.py`
- Create: `tests/test_table_merger.py`

- [ ] **Step 1: 写标签闭合测试**

  缺失 `</tr>`、`</table>` 时应可修复，并记录 `repaired_tags`。

- [ ] **Step 2: 写空单元格保持测试**

  `<td></td>` 必须保留。

- [ ] **Step 3: 写重复表头删除测试**

  相邻切块同一表头重复时只保留一次，但非邻接重复不得删除。

- [ ] **Step 4: 实现 `TableMerger.repair`**

  使用 HTML parser 修复结构，保留原始单元格顺序和空单元格。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_table_merger.py -q`

  Expected: PASS。

### Task 9: 质量门禁与重跑规划

**Files:**

- Create: `finix_restore/quality_gate.py`
- Create: `finix_restore/retry_planner.py`
- Create: `tests/test_quality_gate.py`

- [ ] **Step 1: 写 CSV schema 测试**

  列名错误、行数不一致、重复 `file_name` 都必须失败。

- [ ] **Step 2: 写文件级风险测试**

  空输出、HTML 破损、重复率过高、API 失败率过高要生成明确 risk code。

- [ ] **Step 3: 实现 `QualityGate`**

  输出 `outputs/qc/{stem}.json`，字段包括 `passed`、`risks`、`metrics`。

- [ ] **Step 4: 实现 `RetryPlanner`**

  把 risk code 映射到缩小窗口、增大 overlap、降低并发或表格细网格。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_quality_gate.py -q`

  Expected: PASS。

### Task 10: 端到端流水线与提交文件

**Files:**

- Create: `finix_restore/pipeline.py`
- Create: `finix_restore/submission.py`
- Create: `tests/test_submission.py`
- Modify: `main.py`
- Modify: `run.sh`

- [ ] **Step 1: 写 dry-run E2E 测试**

  使用 2 张 fixture 图片，不调用 API，断言会生成 profile、manifest、空结构 CSV 或明确 dry-run 报告。

- [ ] **Step 2: 实现 `Pipeline.run`**

  串联画像、感知、切块、API、规范化、排序、去重、表格修复、质检和 CSV 写入。

- [ ] **Step 3: 实现断点续跑**

  已有 profile、manifest、api_raw、merged 时优先复用；`--force_api` 才重打 API。

- [ ] **Step 4: 实现 CSV 回读校验**

  写完 `submission.csv` 后立即调用 `QualityGate.check_submission`。

- [ ] **Step 5: 验证**

  Run: `pytest tests/test_submission.py -q`

  Expected: PASS。

### Task 11: 本地训练集评估与消融记录

**Files:**

- Create: `finix_restore/local_eval.py`
- Create: `tests/test_local_eval.py`
- Modify: `docs/reproduce.md`
- Create: `docs/experiments.md`

- [ ] **Step 1: 实现文本编辑距离本地评估**

  对训练集 `mds` 计算字符级归一化 edit distance，作为快速回归指标。

- [ ] **Step 2: 实现 HTML 表格基础统计**

  统计 `<tr>`、`<td>`、空 `<td></td>` 数量差异，作为 TEDS 前置风险指标。

- [ ] **Step 3: 建立消融记录模板**

  写入 `docs/experiments.md`，记录整图、固定滑窗、空白线切块、去重、表格网格、表格修复、质量门禁重跑各实验。

- [ ] **Step 4: 验证**

  Run: `pytest tests/test_local_eval.py -q`

  Expected: PASS。

### Task 12: 复现文档、审计清单与压测

**Files:**

- Create: `docs/reproduce.md`
- Create: `docs/prompt_specs.md`
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: 写复现命令**

  包含环境创建、依赖安装、`.env` 配置、A/B 榜运行命令、输出路径说明。

- [ ] **Step 2: 写合规说明**

  明确唯一 API 为 FinixDoc-VL；`docs/prompt_specs.md` 记录 API 当前无 prompt 参数，所有解析约束通过切块和后处理实现。

- [ ] **Step 3: 补充 `.gitignore`**

  忽略 `.env`、`outputs/`、`*.pyc`、`.pytest_cache/`、`.ruff_cache/`。

- [ ] **Step 4: 压测**

  在 A 榜目录运行：

  ```bash
  time bash run.sh "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" outputs/submission_long_A.csv outputs/long_A configs/default.yaml
  time bash run.sh "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" outputs/submission_table_A.csv outputs/table_A configs/default.yaml
  ```

  Expected: 不崩溃；日志包含每图耗时、切块数、API 调用数、失败重试和质检结果。

---

## 6. 测试策略

### 6.1 单元测试

必须覆盖：

- `test_config.py`：环境变量、YAML 合并、密钥脱敏。
- `test_profiler.py`：长条/表格分类、风险等级。
- `test_chunkers.py`：bbox 覆盖、overlap、manifest 稳定性。
- `test_finix_api.py`：multipart 字段、缓存命中、重试、日志不泄密。
- `test_normalizer.py`：保守格式修复和禁止语义改写。
- `test_reading_order.py`：坐标排序、表格行列排序、目录保护标记。
- `test_dedup.py`：overlap 去重、目录不误删、段落续接。
- `test_table_merger.py`：标签闭合、空 td 保留、重复表头处理。
- `test_quality_gate.py`：文件级风险和 CSV 阻断。
- `test_submission.py`：CSV 可读、列名、行数、文件名集合。

### 6.2 集成测试

本地不应在单元测试中真实调用 API。集成测试分两类：

- `--dry_run`：验证画像、切块、manifest、日志和 CSV schema。
- 小样本真实 API：手动运行 1 张短长条图和 1 张小表格图，确认 API、缓存、合并、质检闭环。

### 6.3 本地评估

训练集有 GT，可用于参数调优：

```bash
python -m finix_restore.local_eval \
  --pred_dir outputs/merged \
  --gt_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --output outputs/metrics/long_eval.json
```

验收指标不是线上分数替代品，但必须能暴露退化：

- 文本长度比。
- 字符级编辑距离。
- 标题行数量差异。
- `<tr>`、`<td>`、空 `<td></td>` 数量差异。
- 疑似重复窗口比例。

---

## 7. 验收标准

### 7.1 功能验收

- `python main.py --dry_run ...` 能在无 API 情况下完成画像、切块和 manifest。
- 配置 `.env` 后，真实 API 小样本能生成非空 Markdown。
- 输出 CSV 可被 `pandas.read_csv` 正确读取。
- CSV 列名严格为 `file_name,ground_truth`。
- CSV 行数与输入图片数一致，无重复、无缺失。
- 每个输出文件都有 `profile`、`manifest`、`api_raw`、`merged`、`qc` 可追溯产物。

### 7.2 质量验收

- 长条文档无明显接缝重复，章节顺序符合 `1 -> 1.1 -> 1.1.1` 等编号连续性。
- 目录内容和正文标题可同时存在，不被去重误删。
- 表格输出保留 HTML `<table>`，空 `<td></td>` 不丢失。
- 表格标签闭合，明显重复表头只在邻接 overlap 处删除。
- 后处理不改写金额、百分比、备案号、条款号。

### 7.3 工程验收

- `pytest -q` 通过。
- `ruff check .` 通过或仅有明确豁免。
- `bash run.sh <input_dir> <output_csv>` 可一键运行。
- `.env`、`outputs/`、API 原始缓存不进入提交包，复现包按比赛要求单独整理。
- `docs/reproduce.md` 能指导评审在干净环境中复现相同流程。

### 7.4 审计验收

- 代码库扫描不包含真实 `apiKey`、Token、Cookie。
- 代码中不存在除 FinixDoc-VL 之外的大模型 API endpoint。
- 没有基于测试文件名的硬编码输出逻辑。
- 日志中每条 `ground_truth` 可追踪到切块坐标、API 原始返回和后处理步骤。

建议扫描命令：

```bash
rg -n "apiKey|sk-|OPENAI|dashscope|anthropic|claude|qwen|gemini|token|cookie" .
```

命中 `.env.example` 的变量名可以接受；真实密钥、其他模型 endpoint 或日志泄露不可接受。

---

## 8. 里程碑

| 阶段 | 目标 | 完成标志 |
| --- | --- | --- |
| M1 基线闭环 | 工程骨架、画像、切块、API、CSV | 小样本真实 API 生成合法 CSV。 |
| M2 长条优化 | 空白线切块、接缝去重、目录保护 | 长条训练样本人检无明显重复/漏接。 |
| M3 表格优化 | 网格切块、HTML 修复、空 td 保留 | 表格训练样本 `<tr>/<td>` 统计接近 GT。 |
| M4 稳定复现 | 质量门禁、重跑、断点续跑、文档 | A 榜目录可一键跑完并保留审计产物。 |
| M5 提交压测 | 并发调优、运行时间控制 | 估算 B 榜 100 张在 3 小时内完成。 |

---

## 9. 风险与缓解

| 风险 | 触发信号 | 缓解 |
| --- | --- | --- |
| API 超时 | `timeout` 或空响应高发 | 降低 `max_chunk_pixels`，窗口缩小 30%，并发降到 1。 |
| 长条漏字 | 边界处句子断裂 | 增大 overlap，空白线切块失败时重跑邻接切块。 |
| 接缝重复 | 重复窗口比例过高 | 启用邻接 overlap prefix/suffix 去重，不全局删重。 |
| 目录误删 | 目录项缺失但正文标题存在 | `toc_block` 保护，目录区不参与普通去重。 |
| 表格错列 | `<td>` 数量骤降或短行多 | 保留空单元格，表格细网格重跑，行级合并。 |
| 复现不一致 | 二次运行输出变化 | 固定配置快照，缓存 API 原始响应，记录 chunk hash。 |
| 凭据泄露 | 日志或提交包出现密钥 | 日志脱敏、`.gitignore`、提交前 `rg` 扫描。 |

---

## 10. 执行顺序建议

1. 先完成 Task 1-5，形成“切块 -> API -> 原始响应缓存”的最小闭环。
2. 再完成 Task 6-8，分别解决 Markdown 顺序、接缝去重和表格结构。
3. 然后完成 Task 9-10，把质量门禁、重跑和最终 CSV 串起来。
4. 最后完成 Task 11-12，做训练集评估、消融、复现文档和压测。

不要先优化复杂规则再跑通 API 闭环；本题主要风险来自超大图切块、API 超时和拼接质量，必须尽早用真实样本验证每个中间产物。
