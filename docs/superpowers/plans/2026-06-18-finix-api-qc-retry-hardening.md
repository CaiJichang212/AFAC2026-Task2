# Finix API QC Retry Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 FinixDoc-VL 调用链路中 HTML 错误页污染缓存、质量门禁不阻断、失败不重跑、抽样不覆盖表格和日志不可追踪的问题，使正式提交 CSV 只在内容质量门禁通过后产出。

**Architecture:** 保持现有 `ImageProfiler -> Chunker -> FinixApiClient -> MarkdownNormalizer -> ReadingOrderResolver -> DedupMerger -> TableMerger -> QualityGate -> SubmissionWriter` 主链路，只在边界增加强校验、状态汇总和有限重跑。API 客户端负责拒绝非法响应并阻止污染 cache；Pipeline 负责汇总文件级 QC、触发重跑并阻断失败提交；CLI 负责提供可覆盖多输入目录的抽样入口。

**Tech Stack:** Python 3.12、requests、Pillow、pandas、pytest、PyYAML、BeautifulSoup。

---

## 0. 审核修订记录

本次审核发现原计划存在以下问题，已在本文中修正：

- 原计划放入了过长的测试函数实现，不符合“计划文档只放关键小段代码”的要求；本文改为测试契约、关键断言和命令。
- `FinixApiClient` 响应校验位置表述不准确；当前源码是在 `_post_chunk()` 返回后由 `parse_chunk()` 写 cache，因此校验应在 `_post_chunk()` 返回 markdown 前完成，确保调用方只会缓存已校验内容。
- `ProcessedFile 或 RunQualitySummary`、`Create or Modify`、Task 8 的“二者择一”存在执行歧义；本文改为唯一接口和唯一实现路线。
- 原计划将 `raw_cache_invalid` 作为 QC 风险，但没有给出明确调用链；本文将旧 cache 处理收敛到 API cache meta 校验，文件级 QC 只关注最终 markdown 内容质量。
- 原计划把 `config.py` 纳入日志增强任务但没有定义配置契约；本文改为由 `Pipeline` 生成 `run_id` 并传入 `FinixApiClient`，避免扩大配置面。
- 原计划没有明确 P0/P1/P2 顺序；本文将阻断污染、阻断提交、重跑和抽样列为 P0，将日志增强列为 P1，并发列为 P2。

## 1. 需求来源与边界

需求来源：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/问题分析和解决方案-20260618.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/test.sh` 第 9-15 行
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/run_A_10`
- 源码目录：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore`

强约束：

- 只允许调用 FinixDoc-VL，不接入其他大模型 API。
- 不读取、打印或写入 `.env` 中真实密钥。
- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data` 下原始数据。
- 不按 A/B 测试文件名写特判逻辑。
- `outputs/` 仅作为运行产物目录，不把旧污染 cache 视为可信输入。

非目标：

- 不重写表格拼接算法。
- 不重写大段去重算法。
- 不实现线上评分指标。
- 不在计划文档中放大段完整实现。

## 2. 文件结构与职责

### 2.1 生产代码

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
  - 检测并拒绝 HTTP 200 HTML 网关/繁忙页。
  - 写入带校验版本的 API cache meta。
  - 记录不含密钥的请求结果日志。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
  - 检测最终 markdown 中的完整 HTML 错误页。
  - 写出运行级 `qc/summary.json`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
  - 新增 `ProcessedFile` 数据结构。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - 汇总文件级 QC。
  - QC 失败时阻断正式 CSV。
  - 接入有限重跑。
  - 为运行生成 `run_id`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
  - 支持 HTML 错误页、API 失败率、短输出等风险到重跑动作的映射。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py`
  - 新增 `--limit_per_dir`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
  - `RunConfig` 新增 `limit_per_dir`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/test.sh`
  - 小样本命令改为每个输入目录各取样，覆盖长图和表格。

### 2.2 测试文件

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py`

## 3. 接口契约

### 3.1 API 响应校验

`FinixApiClient._post_chunk()` 必须只返回已校验 markdown；`parse_chunk()` 只能缓存 `_post_chunk()` 成功返回的内容。

关键接口：

```python
def _validate_markdown_response(self, markdown: str) -> None:
    """Raise FinixApiError when a response is a full HTML gateway/error page."""
```

非法响应规则：

- 以 `<!doctype html` 或 `<html` 开头。
- 同时包含 `<head` 与 `<body`。
- 包含 `服务器繁忙`、`顾客太多`、`J_retry_link`、`showTextWait`、`支付宝版权所有`。
- 包含 `alipayobjects.com` 且包含 `<html`。

合法响应规则：

- 普通 Markdown 允许。
- FinixDoc-VL 返回的 `<table>...</table>` 表格片段允许。

### 3.2 API cache meta

新写入的 `api_raw/{stem}/{chunk_id}.json` 必须包含：

```json
{
  "chunk_id": "string",
  "image_sha1": "string",
  "api_url": "string",
  "content_validated": true,
  "validator_version": 1,
  "response_sha1": "string"
}
```

读取 cache 时必须校验：

- `content_validated is True`
- `validator_version == 1`
- `response_sha1 == sha1(raw_md_text)`
- `chunk_id`、`image_sha1`、`api_url` 与当前请求一致

不满足任一条件时视为 cache miss，并重新请求 API；不得复用旧污染结果。

### 3.3 Pipeline 文件处理结果

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py` 新增：

```python
@dataclass(frozen=True)
class ProcessedFile:
    file_name: str
    markdown: str
    quality: QualityReport
    rerun_count: int = 0
```

Pipeline 契约：

- 非 dry-run 模式下，任意 `ProcessedFile.quality.passed is False` 时，不写正式 `output_csv`。
- 失败时写出 `{work_dir}/qc/summary.json`，然后抛出 `PipelineError`。
- dry-run 可以写空 CSV，但 summary 必须标记 `dry_run=true`。
- resume 命中 `merged/{stem}.md` 时仍需执行 QC，并在 metrics 中记录 `from_merged_cache=1`。

### 3.4 抽样契约

新增 CLI 参数：

```bash
--limit_per_dir 5
```

取样顺序：

1. 每个 `--input_dir` 内按文件名排序。
2. 若设置 `--limit_per_dir N`，每个目录取前 N 张。
3. 合并各目录样本。
4. 若同时设置 `--limit M`，再做全局截断。

### 3.5 重跑契约

`RetryPlanner.plan()` 返回字段固定为：

```python
{
    "rerun": bool,
    "force_api": bool,
    "window_scale": float,
    "overlap_scale": float,
    "table_grid_scale": float,
    "concurrency": int,
    "reasons": list[str],
}
```

P0 阶段只要求支持：

- `service_busy_html`、`full_html_page`：`force_api=True`、`concurrency=1`、`rerun=True`
- `api_failure_ratio_high`：`concurrency=1`、`rerun=True`
- `empty_output`、`too_short`：`rerun=True`

`window_scale`、`overlap_scale`、`table_grid_scale` 可以先只写入计划结果，不必在 P0 立刻重切图片；真正重切可另开计划。

## 4. 实施任务

### Task 1: 阻断 HTML 错误页进入 API cache

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`

- [ ] **Step 1: 写失败测试**

新增测试：`test_http_200_service_busy_html_is_retryable_and_not_cached`

断言：

- HTTP 200 且响应为 `<!DOCTYPE html>...服务器繁忙...J_retry_link...` 时抛出 `FinixApiError`。
- `api_raw/doc/chunk-a.md` 不存在。
- `run.jsonl` 不包含 API key。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py::test_http_200_service_busy_html_is_retryable_and_not_cached -q
```

Expected: FAIL。

- [ ] **Step 2: 写保护测试**

新增测试：`test_html_table_fragment_is_valid_markdown_response`

断言：

- `<table><tr><td>保障责任</td></tr></table>` 不触发 HTML 错误页检测。
- raw markdown 被写入 cache。

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py::test_html_table_fragment_is_valid_markdown_response -q
```

Expected: PASS。

- [ ] **Step 3: 实现响应校验**

在 `finix_api.py` 中增加 HTML 错误页 marker 常量和 `_validate_markdown_response()`。关键位置：

```diff
 markdown = self._extract_markdown(str(text))
+self._validate_markdown_response(markdown)
 if not markdown:
     raise FinixApiError("empty response")
 return markdown
```

- [ ] **Step 4: 跑测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py -q
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py
git commit -m "fix: reject finix html error responses"
```

### Task 2: 强化 API cache meta

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`

- [ ] **Step 1: 写失败测试**

新增测试：`test_cache_without_validation_meta_is_ignored`

断言：

- 旧 meta 只含 `chunk_id`、`image_sha1`、`api_url` 时不命中 cache。
- 客户端重新请求 API。
- 返回新响应并覆盖 cache meta。

Expected before implementation: FAIL。

- [ ] **Step 2: 写新 meta 测试**

新增或扩展测试：`test_cache_meta_records_validation_fields`

断言 meta 包含：

- `content_validated is True`
- `validator_version == 1`
- `response_sha1` 等于 raw markdown 的 sha1

- [ ] **Step 3: 实现 meta 校验**

在 `finix_api.py` 中定义：

```python
_CACHE_VALIDATOR_VERSION = 1
```

`_read_cache()` 校验版本和 sha1；`_write_cache()` 写入新字段。旧 meta 应视为 miss。

- [ ] **Step 4: 更新既有 cache hit 测试**

`test_cache_hit_uses_raw_response_without_request` 的手写 meta 必须加入新字段。

- [ ] **Step 5: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py
git commit -m "fix: validate finix api cache metadata"
```

### Task 3: 增强 QualityGate HTML 风险检测

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`

- [ ] **Step 1: 写失败测试**

新增测试：`test_quality_gate_flags_service_busy_html_page`

断言：

- 完整 HTML 繁忙页触发 `service_busy_html`。
- 完整 HTML 页触发 `full_html_page`。
- QC JSON 写入相同风险。

Expected before implementation: FAIL。

- [ ] **Step 2: 写保护测试**

新增测试：`test_quality_gate_allows_html_table_fragment`

断言合法 `<table>...</table>` 不触发 `service_busy_html` 或 `full_html_page`。

- [ ] **Step 3: 实现检测**

在 `quality_gate.py` 中增加：

```python
def detect_forbidden_html(markdown: str) -> list[str]:
    ...
```

`check_file()` 将该函数返回的风险合并进 `risks`。

- [ ] **Step 4: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py
git commit -m "fix: flag gateway html in quality gate"
```

### Task 4: 阻断 QC 失败的正式提交

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 写失败测试**

新增测试：`test_pipeline_blocks_submission_when_file_qc_fails`

断言：

- Fake client 返回 HTML 繁忙页。
- `Pipeline.run()` 抛出 `PipelineError`，错误信息包含 `quality gate failed`。
- `output_csv` 不存在。
- `{work_dir}/qc/summary.json` 存在，并包含失败文件和风险计数。

Expected before implementation: FAIL。

- [ ] **Step 2: 新增 ProcessedFile**

在 `models.py` 增加 `ProcessedFile`，字段按 3.3 契约执行。

- [ ] **Step 3: 新增 summary 写出**

在 `QualityGate` 中增加：

```python
def write_summary(self, processed_files: Sequence[ProcessedFile], output_csv: Path | None) -> QualityReport:
    ...
```

summary 至少包含：

- `passed`
- `failed_files`
- `risk_counts`
- `file_count`
- `output_csv`

- [ ] **Step 4: 改造 Pipeline**

要求：

- `_process_image()` 返回 `ProcessedFile`。
- `Pipeline.run()` 先收集所有 `ProcessedFile`。
- 写 `qc/summary.json`。
- 任意文件失败时不调用 `SubmissionWriter().write()`。
- 全部通过时才写正式 CSV。

- [ ] **Step 5: 更新旧测试**

`test_pipeline_records_retry_exhausted_chunk_failure_and_still_writes_csv` 改为：

- 期望 `PipelineError`。
- 断言 `submission.csv` 不存在。
- 断言 QC 和 summary 存在。

- [ ] **Step 6: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/models.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py
git commit -m "fix: block submission on file quality failures"
```

### Task 5: 接入有限重跑

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 扩展 RetryPlanner 测试**

新增断言：

- `service_busy_html` 和 `full_html_page` 返回 `rerun=True`、`force_api=True`、`concurrency=1`。
- 达到 `max_reruns_per_file` 后返回 `rerun=False`。

Expected before implementation: FAIL。

- [ ] **Step 2: 实现 RetryPlanner 契约**

按 3.5 固定返回字段，不新增未使用的风险名称。

- [ ] **Step 3: 写 Pipeline 重跑测试**

新增测试：`test_pipeline_reruns_once_after_retryable_quality_failure`

断言：

- Fake client 第一次返回 HTML，第二次返回 `# ok`。
- `quality.max_reruns_per_file=1`。
- 最终生成 CSV。
- summary 中该文件 `rerun_count == 1`。

- [ ] **Step 4: 改造 Pipeline 重跑循环**

建议拆分：

```python
def _process_image_once(self, image_path: Path, force_api: bool = False) -> ProcessedFile:
    ...
```

`_process_image()` 负责调用 `RetryPlanner`，最多重跑 `quality.max_reruns_per_file` 次。

- [ ] **Step 5: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py
git commit -m "fix: rerun retryable quality failures"
```

### Task 6: 增加 `--limit_per_dir` 覆盖多输入目录

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/test.sh`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py`

- [ ] **Step 1: 写抽样测试**

新增测试：`test_limit_per_dir_samples_each_input_directory`

断言：

- 输入目录 A 有 `a0.png,a1.png,a2.png`，目录 B 有 `b0.png,b1.png,b2.png`。
- `limit_per_dir=2` 时，`Pipeline._list_images()` 返回 `a0,a1,b0,b1`。
- 同时设置 `limit=3` 时，最终返回 `a0,a1,b0`。

Expected before implementation: FAIL。

- [ ] **Step 2: 扩展 CLI 和 RunConfig**

关键 diff：

```diff
 parser.add_argument("--limit", type=int)
+parser.add_argument("--limit_per_dir", type=int)
```

`RunConfig` 新增 `limit_per_dir: int | None = None`。

- [ ] **Step 3: 修改 `_list_images()`**

按 3.4 契约实现。不要根据目录名判断长图或表格。

- [ ] **Step 4: 更新 `test.sh`**

将第 9-15 行的小样本命令改为 `--limit_per_dir 5`，输出目录建议改为 `outputs/run_A_smoke`，避免误用旧 `run_A_10` cache。

- [ ] **Step 5: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/test.sh \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_cli_sampling.py
git commit -m "fix: sample each input directory in smoke runs"
```

### Task 7: 增强日志与 summary 可追踪性

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py`

- [ ] **Step 1: 写 API 日志字段测试**

断言 `run.jsonl` 的 `api_call` 包含：

- `run_id`
- `response_sha1`
- `response_chars`
- `content_validated`

并断言日志中不包含 `api_key` 或测试伪 key。

- [ ] **Step 2: 写 summary 字段测试**

断言 `qc/summary.json` 包含：

- `passed`
- `failed_files`
- `risk_counts`
- `file_count`
- 每个文件的 `rerun_count`

- [ ] **Step 3: 实现 run_id**

`Pipeline.__init__` 生成一次 `run_id`，创建 `FinixApiClient` 时传入。`FinixApiClient.__init__` 增加可选参数：

```python
run_id: str | None = None
```

- [ ] **Step 4: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py
git commit -m "chore: add finix run trace fields"
```

### Task 8: 实现保守有界并发

**Priority:** P2。只有 Task 1-7 全部通过后再执行。

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`

- [ ] **Step 1: 明确唯一并发接口**

将 `FinixApiClient.parse_chunks()` 改为唯一批量接口：

```python
def parse_chunks(self, chunks: list[Chunk], force_api: bool = False) -> tuple[list[ChunkText], int]:
    """Return chunk texts in input order and failed chunk count."""
```

不保留另一套批量错误处理路线。

- [ ] **Step 2: 写并发测试**

新增测试：`test_parse_chunks_returns_results_in_input_order_with_failures`

断言：

- 返回顺序与输入 chunks 一致。
- 单个 chunk 失败时对应 markdown 为空，`failed_chunks == 1`。
- `max_workers == client.concurrency` 可通过注入 executor factory 或 monkeypatch 验证。

- [ ] **Step 3: 实现有界并发**

使用 `ThreadPoolExecutor(max_workers=self.concurrency)`。注意：

- `requests.Session` 共享线程安全性有限；实现时优先每个任务使用同一个 session 的 `post` 仍需测试，若出现问题则改为每线程独立 session。
- 每个 chunk 内仍沿用现有 retry 逻辑。
- 日志不打印密钥。

- [ ] **Step 4: Pipeline 使用批量接口**

`Pipeline._parse_chunks()` 调用 `client.parse_chunks()`，不再手写串行循环。

- [ ] **Step 5: 跑测试并提交**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py \
       /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py -q
```

Commit:

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
        /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py
git commit -m "perf: parse finix chunks with bounded concurrency"
```

## 5. 端到端验收

### 5.1 单元测试

```bash
pytest -q
```

Expected: 全部通过。

### 5.2 格式检查

```bash
git diff --check
```

Expected: 无输出，退出码 0。

### 5.3 小样本运行

使用新的独立输出目录，避免复用 `run_A_10` 旧污染 cache：

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  --work_dir outputs/run_A_smoke_fixed \
  --output_csv outputs/run_A_smoke_fixed/submission_A_smoke_fixed.csv \
  --limit_per_dir 5 \
  --force_api
```

Expected:

- 全部文件通过 QC 时生成 `outputs/run_A_smoke_fixed/submission_A_smoke_fixed.csv`。
- 任意文件失败时不生成正式 CSV，并写出 `outputs/run_A_smoke_fixed/qc/summary.json`。

### 5.4 异常 HTML 扫描

```bash
rg -n "J_retry_link|showTextWait|服务器繁忙|顾客太多|<!DOCTYPE html>" \
  outputs/run_A_smoke_fixed/api_raw \
  outputs/run_A_smoke_fixed/normalized \
  outputs/run_A_smoke_fixed/merged
```

Expected: 无命中。

### 5.5 CSV 校验

仅当 CSV 存在时执行：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

csv_path = Path("outputs/run_A_smoke_fixed/submission_A_smoke_fixed.csv")
df = pd.read_csv(csv_path)
assert list(df.columns) == ["file_name", "ground_truth"]
assert len(df) == 10
assert not df["file_name"].duplicated().any()
assert df["ground_truth"].fillna("").str.len().gt(0).all()
print("csv ok")
PY
```

Expected: 输出 `csv ok`。

## 6. 旧污染产物处理

修复后不要继续信任 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/run_A_10` 的旧 cache。先定位污染产物：

```bash
rg -l "J_retry_link|showTextWait|服务器繁忙|顾客太多|<!DOCTYPE html>" \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/run_A_10/api_raw \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/run_A_10/normalized \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/run_A_10/merged
```

推荐使用新的 `work_dir` 重跑。若必须复用旧目录，只删除 `outputs/` 下对应 stem 的运行产物，不碰 `data/`。

## 7. Self-Review

Spec coverage:

- HTML 错误页污染：Task 1、Task 2、Task 3。
- QC 不阻断：Task 4。
- 失败不重跑：Task 5。
- `--limit 10` 不覆盖表格：Task 6。
- 日志不可追踪：Task 7。
- 并发配置未生效：Task 8。

Placeholder scan:

- 本计划无占位项、无未定义接口。
- 代码块只用于关键契约、关键 diff 和验收命令。
- 大段完整实现留给源码和 PR。

Type consistency:

- `QualityReport` 沿用现有模型。
- `ProcessedFile` 在 `models.py`、`quality_gate.py`、`pipeline.py` 中使用。
- `limit_per_dir` 在 `cli.py`、`config.py`、`pipeline.py` 中命名一致。
- `FinixApiClient.parse_chunks()` 在 Task 8 后统一返回 `tuple[list[ChunkText], int]`。
