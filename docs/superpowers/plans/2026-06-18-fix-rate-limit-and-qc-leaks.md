# 限流污染与 QC 漏检修复 实施计划

> 本计划面向 [`finix_restore`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore) 现有工程，问题清单见 [存在的问题20260618-3.md](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/存在的问题20260618-3.md)。计划内只放接口契约、关键约束与最小提示性 diff；完整实现进入代码库与对应 PR。

**Goal:** 阻断"限流 HTML 错误页"被当成成功结果落入缓存与提交 CSV，并将 51% 的 retryable_error 显著降低，让大图(long_strip)在重试 / 退避 / 去重 / QC 链路上达到可上榜水准。

**Architecture:**
- 在 `finix_api.FinixApiClient` 引入"响应内容质检 + 限流分类 + 用户冷却 + 抖动退避"，让 HTML 错误页变为 retryable 而非 ok。
- 在 `quality_gate.QualityGate` 增加 HTML 残留与"伪成功"检测；`Pipeline.run` 末端遇到 `html_error_leak` 直接抛错，禁止生成提交。
- `SubmissionWriter` 显式 `quoting=csv.QUOTE_ALL` 并在写后做内容长度往返校验。
- 接通 [`retry_planner.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/retry_planner.py)：`Pipeline._process_image` 在 QC 不通过时按 plan 缩 window/扩 overlap 重切重跑，最多 `max_reruns_per_file` 次。
- `Pipeline._parse_chunks` 引入 `ThreadPoolExecutor`，按 `len(user_ids) * per_user_concurrency` 真正并发，client 在 Pipeline 级别复用。
- `dedup.DedupMerger` 提供"行级指纹 + 滚动哈希 LCS"分支，long_strip 默认走该分支，避免 SequenceMatcher 在重叠区漏判。
- 引入"中毒缓存清理脚本"（一次性 CLI 子命令），不修改 `data/`，仅清理 `work_dir` 下 `api_raw/*` 与 `merged/*`。

**Tech Stack:** Python 3.11+，`requests`、`pandas`、`PIL`，仅允许调用 FinixDoc-VL；测试使用 `pytest`（见 [`pytest.ini`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/pytest.ini)）。本地小模型若引入须 < 10M 参数（本计划不引入）。

---

## 文件结构（创建 / 修改）

| 路径 | 角色 | 变更性质 |
|---|---|---|
| [`finix_restore/finix_api.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py) | API 客户端 | 修改：HTML 检测 / 用户冷却 / 退避 / 缓存写入门槛 / 日志增强 |
| [`finix_restore/quality_gate.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py) | QC | 修改：HTML 残留检测 / 阈值参数化 |
| [`finix_restore/pipeline.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py) | 编排 | 修改：阻断 leak / 复用 client / 接通 RetryPlanner / 真并发 / `_read_merged` 守卫 |
| [`finix_restore/submission.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/submission.py) | CSV 写入 | 修改：`QUOTE_ALL` + 长度往返校验 |
| [`finix_restore/dedup.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py) | 去重合并 | 修改：long_strip 行级指纹合并分支 |
| [`finix_restore/cli.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py) | CLI | 修改：新增 `--purge-poisoned` 子动作（最小入口） |
| [`finix_restore/cache_cleaner.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cache_cleaner.py) | 中毒缓存清理 | 新增：纯函数 + 一次性脚本入口 |
| [`configs/default.yaml`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml) | 默认配置 | 修改：`max_retries=6`、并发与冷却参数、`quality.html_leak_markers` |
| [`tests/test_finix_api.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py) | 单测 | 修改：新增 HTML 限流 / 冷却 / 抖动 / 缓存拒写 用例 |
| [`tests/test_quality_gate.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_quality_gate.py) | 单测 | 修改：新增 `html_error_leak` 检测 |
| [`tests/test_submission.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py) | 单测 | 修改：新增 QUOTE_ALL 与长度往返 |
| [`tests/test_dedup.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_dedup.py) | 单测 | 修改：新增"VLM 微差异下 long_strip 重叠去重"用例 |
| `tests/test_pipeline_retry.py` | 单测 | 新增：QC 失败 → RetryPlanner 重跑 |
| `tests/test_cache_cleaner.py` | 单测 | 新增：HTML 标记命中 → 删 raw + meta + merged |

> 不修改：[`data/`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2)、[`docs/`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs)（除新增本计划外）、`.env`。

---

## 强约束与不变量（评审与执行必读）

1. **唯一大模型接口**：仅 FinixDoc-VL；本计划不引入任何外部模型/Embedding。
2. **密钥不落盘**：`run.jsonl` 增字段时严禁写入 `apiKey` / `userId` 之外的敏感信息；现有 `_log` 已规避。
3. **`data/` 只读**：所有清理仅作用于 `paths.work_dir` 子目录。
4. **不针对测试集硬编码**：HTML 标记列表通过 config 注入，禁止以 `file_name` 做特判分支。
5. **缓存键必须包含质检**：`_write_cache` 的内容若命中 leak 标记则**不写入**，防止 `--resume` 永久固化错误。
6. **CSV 列名锁死** `["file_name", "ground_truth"]`、行数 == 期望文件数、`file_name` 唯一。
7. **真并发上限**：`min(api.concurrency, len(user_ids) * per_user_concurrency)` 不变，client 在 Pipeline 内只构造一次。
8. **行为兼容**：现有通过的所有单测（`pytest -q`）必须继续通过；新增行为以参数默认开启但可关闭。

---

## 接口契约（关键 API/数据）

### FinixApiClient（[`finix_api.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py)）

新增 / 调整签名：

```python
class FinixApiClient:
    def __init__(
        self,
        ...,
        max_retries: int = 6,
        backoff_base_seconds: float = 2.0,
        backoff_cap_seconds: float = 60.0,
        backoff_jitter_seconds: float = 2.0,
        cooldown_seconds: float = 30.0,
        html_leak_markers: tuple[str, ...] = (
            "<!doctype html>", "<html", "顾客太多", "服务器繁忙",
        ),
        ...,
    ) -> None: ...

    # 行为约束：
    # - _post_chunk 收到 Content-Type 含 "text/html" 或正文命中任一 marker → raise FinixApiError("retryable: html response")
    # - 返回 JSON 中 success=False / code 含 ("rate","busy","limit") → retryable
    # - 退避：sleep_for = min(cap, base ** retry_index) + uniform(0, jitter)
    # - 冷却：retryable 触发时把当次 user_id 加入 _disabled_user_ids，下一次 _next_user_id 跳过；
    #   若全部禁用 → sleep(cooldown_seconds) 并清空
    # - _write_cache 在写入前调用 _looks_like_leak(markdown) 守卫；命中 → 抛 retryable 不写盘
    # - 日志新增字段：response_bytes, content_type, is_html, http_status
```

### QualityGate（[`quality_gate.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/quality_gate.py)）

```python
class QualityGate:
    def __init__(self, paths, ..., html_leak_markers: tuple[str, ...] = (...)) -> None: ...
    def check_file(self, file_name, markdown, doc_type, chunk_count, failed_chunks) -> QualityReport:
        # 命中任一 marker → risks.append("html_error_leak")
        # passed = not risks
```

### Pipeline（[`pipeline.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py)）

- `Pipeline.__init__` 创建一个 `FinixApiClient` 复用整轮；`_parse_chunks` 改为 `ThreadPoolExecutor(max_workers=client.concurrency)`。
- `_process_image` 在 QC 后：
  - `report.passed=False` 且 `rerun_count < max_reruns_per_file` → 调 `RetryPlanner.plan` → 按 `window_scale / overlap_scale` 调 chunk 配置 → 删除该文件 `chunks_dir/<stem>` 与 `api_raw/<stem>` 与 `merged/<stem>.md` → 重跑。
  - 任一 file 最终 `risks` 含 `html_error_leak` → `raise PipelineError("html_error_leak: <file>")`，不写 CSV。
- `_read_merged` 命中 cached 文件后必须再做一次 leak 检测；命中即视为未命中并删除该缓存（兼容 #4）。

### SubmissionWriter（[`submission.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/submission.py)）

```python
import csv
df.to_csv(output_csv, index=False, encoding="utf-8",
          lineterminator="\n", quoting=csv.QUOTE_ALL)
# _validate 中：再 read_csv 后比较每行 ground_truth 长度 == 入参 rows 对应字段长度
```

### DedupMerger（[`dedup.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/dedup.py)）

新增策略入口：

```python
class DedupMerger:
    def __init__(self, ..., long_strategy: str = "line_lcs") -> None: ...
    # long_strategy ∈ {"char_match", "line_lcs"}；long_strip 默认 "line_lcs"
    # line_lcs：按 \n 切分→去除全空白行→对每行做规范化指纹（去掉中文空白、归一标点、lower）→
    #          在 prev tail 与 cur head 上做 LCS（窗口 = window_chars_long // avg_line_len，下限 16），
    #          若公共行连续 ≥ 3 行或覆盖 head 起始 ≥ 60% → 以行级偏移移除前缀
```

### CacheCleaner（新增 [`finix_restore/cache_cleaner.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cache_cleaner.py)）

```python
def purge_poisoned(work_dir: Path, markers: Sequence[str]) -> dict[str, int]:
    """扫描 work_dir/api_raw/**/*.md 与 work_dir/merged/*.md，
    若文件内容包含任一 marker（小写比对）：
      - 删除该 .md 与同目录同名 .json
      - 若是 merged，删除 work_dir/qc/<stem>.json 同步失效
    返回各类删除计数。绝不触碰 data/、不递归到 work_dir 之外。"""
```

CLI：[`finix_restore/cli.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py) 新增子动作 `--purge-poisoned`，命中即只跑清理并退出（不需要 API key）。

---

## 配置变更（[`configs/default.yaml`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml)）

```yaml
api:
  max_retries: 6                # 3 → 6
  backoff_base_seconds: 2.0
  backoff_cap_seconds: 60.0
  backoff_jitter_seconds: 2.0
  cooldown_seconds: 30.0
quality:
  html_leak_markers: ["<!doctype html>", "<html", "顾客太多", "服务器繁忙"]
  max_reruns_per_file: 2        # 已存在，确认接通 RetryPlanner
merge:
  long_strategy: "line_lcs"
```

---

## 任务分解（每步 2–5 分钟）

> 每个任务遵循 TDD：先红再绿，最后 commit。完整代码在 PR 中提交。

### Task 1：限流 HTML 识别为 retryable（[`finix_api.py`](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py)）

**Files:** Modify `finix_restore/finix_api.py`；Test `tests/test_finix_api.py`

- [ ] 写失败用例：`FakeResponse(200, "<!DOCTYPE html>...顾客太多...")` → `parse_chunk` 抛 `FinixApiError`，且 `api_raw/` 下不写文件，`run.jsonl` 状态为 `retryable_error`。
- [ ] 写失败用例：`FakeResponse` 带 `headers={"content-type": "text/html"}` 也走 retryable（需要把 FakeResponse 加 `headers`）。
- [ ] 让 `_post_chunk` 读 `response.headers.get("Content-Type", "")` 与正文 marker；命中即 raise retryable。
- [ ] `_extract_markdown` 末端兜底也加 marker 检测，避免 fence 包装绕过。
- [ ] 跑测试：`pytest tests/test_finix_api.py -v`。
- [ ] commit：`fix(finix_api): treat html/limit responses as retryable`。

### Task 2：缓存写入前 leak 守卫

**Files:** Modify `finix_restore/finix_api.py`；Test `tests/test_finix_api.py`

- [ ] 写失败用例：构造 `_post_chunk` 通过补丁返回 HTML 文本，断言 `_write_cache` 不会执行（`raw_path.exists() is False`）且抛 retryable。
- [ ] 在 `_write_cache` 入口或 `parse_chunk` 成功分支加 `_looks_like_leak`，命中转为 retryable 并不写缓存。
- [ ] commit：`fix(finix_api): block leaked html from cache`。

### Task 3：用户冷却 + 抖动退避

**Files:** Modify `finix_restore/finix_api.py`；Test `tests/test_finix_api.py`

- [ ] 写失败用例：3 个 user_ids、连续 3 次 retryable → 三个 user 都进 `_disabled_user_ids`，第 4 次触发 `cooldown_seconds` sleep（用 fake `sleep` 计数断言）。
- [ ] 写失败用例：抖动退避 `sleep` 调用次数 == retry 次数；可注入 `random.uniform` 让其确定性。
- [ ] 实现 `_next_user_id` 跳过禁用、全禁则全局冷却清空；`max_retries` 默认 6。
- [ ] commit：`fix(finix_api): per-user cooldown and jittered backoff`。

### Task 4：日志增强（response_bytes / content_type / is_html / http_status）

**Files:** Modify `finix_restore/finix_api.py`；Test `tests/test_finix_api.py`

- [ ] 写失败用例：成功调用后 `run.jsonl` 末行包含上述字段。
- [ ] 在 `_log_api_call` 增加可选字段，从 `_post_chunk` 透传；缓存命中分支字段为空字符串/0。
- [ ] commit：`feat(finix_api): enrich api_call logs`。

### Task 5：QC 增加 `html_error_leak`，Pipeline 阻断提交

**Files:** Modify `finix_restore/quality_gate.py`、`finix_restore/pipeline.py`；Test `tests/test_quality_gate.py`、`tests/test_pipeline_retry.py`(新增)

- [ ] QC 单测：含 `<!DOCTYPE html>` 的 markdown → `risks` 含 `html_error_leak`，`passed=False`。
- [ ] Pipeline 单测：构造 mock client 让某文件 markdown 命中 leak → `Pipeline.run` 抛 `PipelineError("html_error_leak:...")` 且 CSV 未生成。
- [ ] 实现 `QualityGate.html_leak_markers` 注入与检测；`Pipeline.run` 末尾遍历 `qc_dir/*.json`，命中即 raise。
- [ ] commit：`fix(qc): block html error leaks before submission`。

### Task 6：缓存命中也走 leak 守卫（清除中毒 merged）

**Files:** Modify `finix_restore/pipeline.py`；Test `tests/test_pipeline_retry.py`

- [ ] 写失败用例：`merged/<stem>.md` 已存在且含 `顾客太多` → `_read_merged` 视为未命中并删除文件，触发重新切块走 API。
- [ ] 在 `_read_merged` 中读出后做 `any(m in text for m in markers)` 检测。
- [ ] commit：`fix(pipeline): re-validate cached merged before resume`。

### Task 7：CSV `QUOTE_ALL` + 内容长度往返校验

**Files:** Modify `finix_restore/submission.py`；Test `tests/test_submission.py`

- [ ] 写失败用例：含 `\n` / `"` / `,` 的 ground_truth → `to_csv` 后 `read_csv` 回来后每行长度与原 rows 对应字段长度一致；列名仍为 `["file_name","ground_truth"]`。
- [ ] 改 `to_csv(..., quoting=csv.QUOTE_ALL)`；`_validate` 增加长度比对，不一致则 `risks.append("csv_value_length_mismatch")`。
- [ ] commit：`fix(submission): force QUOTE_ALL and validate roundtrip`。

### Task 8：DedupMerger long_strip 行级 LCS

**Files:** Modify `finix_restore/dedup.py`；Test `tests/test_dedup.py`

- [ ] 写失败用例：两个 long_strip 相邻 chunk，重叠区相同行有 1 个错字（如全角逗号变半角），现有逻辑 `duplication_ratio > 0.3`，新逻辑应 < 0.05。
- [ ] 实现 `_line_lcs_overlap`（行规范化 + 连续公共行 ≥3 → 当作重叠并按行偏移裁剪）。
- [ ] 默认 `long_strategy="line_lcs"`；保留 `char_match` 兼容路径供回退。
- [ ] commit：`fix(dedup): line-level lcs for long_strip overlap`。

### Task 9：接通 RetryPlanner（QC 失败重跑）

**Files:** Modify `finix_restore/pipeline.py`；Test `tests/test_pipeline_retry.py`

- [ ] 写失败用例：mock QC 第一次返回 `high_duplication`，第二次通过 → `_chunk` 被调用 2 次，且第二次的 `long_window_height` ≈ 第一次 × `window_scale`。
- [ ] `_process_image` 包入 `for rerun in range(max_reruns_per_file + 1)`；每次重跑前清理该文件下 `chunks_dir/<stem>`、`api_raw/<stem>`、`merged/<stem>.md`，并按 plan 重建 chunker 配置（直接新建临时 RunConfig.chunk dict）。
- [ ] commit：`feat(pipeline): rerun via RetryPlanner on qc failure`。

### Task 10：Pipeline 真并发 + client 复用

**Files:** Modify `finix_restore/pipeline.py`；Test `tests/test_pipeline_retry.py`

- [ ] 写失败用例（确定性）：5 个 chunk + 2 个 user_ids → 并发 ≤ 2，user_id 轮询且重试不重复落到同一个被禁用 user。可通过 `concurrent.futures.ThreadPoolExecutor` + `FakeSession` 计数验证。
- [ ] `Pipeline.__init__` 构造一次 `FinixApiClient` 并保存；`_parse_chunks` 用 `ThreadPoolExecutor(max_workers=client.concurrency)`；保持失败计数与顺序（按 `chunks` 索引收集结果）。
- [ ] commit：`feat(pipeline): real concurrency and shared client`。

### Task 11：缓存清理工具 + CLI

**Files:** Create `finix_restore/cache_cleaner.py`、Modify `finix_restore/cli.py`；Test `tests/test_cache_cleaner.py`

- [ ] 写失败用例：构造 `work_dir/api_raw/doc/x.md` 含 marker、对应 `x.json` 与 `merged/doc.md` → `purge_poisoned` 后三者全删，正常文件保留；返回 `{"raw":1,"merged":1,"qc":1}`。
- [ ] 实现 `purge_poisoned`；CLI 加 `--purge-poisoned`：当指定该参数时不调用 `Pipeline.run`，只跑清理打印结果并退出 0。
- [ ] commit：`feat(cli): purge-poisoned subcommand`。

### Task 12：配置与 README 同步

**Files:** Modify `configs/default.yaml`、`README.md`

- [ ] 把新参数填入 `default.yaml`（见上方"配置变更"）。
- [ ] `README.md` 在"运行 / 排错"章节加一段：限流污染 → `python -m finix_restore.cli --purge-poisoned --work_dir outputs/run_A_10` 后再 `--resume` 重跑。
- [ ] commit：`docs: configuration and recovery guide`。

### Task 13：端到端冒烟（仅 1 张 long_strip）

**Files:** 不新增产物。本步骤仅运行命令验证。

- [ ] 选 `outputs/run_A_10` 内最小 long_strip 图，先 `--purge-poisoned` 清理，再 `--limit 1` 跑全链路。
- [ ] 校验：`run.jsonl` 不再有 `is_html=true` 的 ok 记录；`qc/*.json` 不含 `html_error_leak`；`submission.csv` `pandas.read_csv` 行数与 ground_truth 长度 == 文件长度。
- [ ] 不 commit（仅验证）。

---

## 测试与验收

### 单元测试覆盖矩阵

| 用例 | 文件 | 关注点 |
|---|---|---|
| HTML 200 → retryable | `tests/test_finix_api.py` | Task 1 |
| Content-Type=text/html → retryable | `tests/test_finix_api.py` | Task 1 |
| HTML 不写缓存 | `tests/test_finix_api.py` | Task 2 |
| user_id 冷却 + 全禁后全局 sleep | `tests/test_finix_api.py` | Task 3 |
| 退避抖动 sleep 序列 | `tests/test_finix_api.py` | Task 3 |
| `run.jsonl` 字段齐全 | `tests/test_finix_api.py` | Task 4 |
| QC `html_error_leak` | `tests/test_quality_gate.py` | Task 5 |
| Pipeline leak → raise | `tests/test_pipeline_retry.py` | Task 5 |
| 缓存 merged 含 leak → 重跑 | `tests/test_pipeline_retry.py` | Task 6 |
| CSV QUOTE_ALL 往返长度 | `tests/test_submission.py` | Task 7 |
| Dedup long_strip 微差异 | `tests/test_dedup.py` | Task 8 |
| RetryPlanner 重跑 | `tests/test_pipeline_retry.py` | Task 9 |
| 真并发 + user 轮询 | `tests/test_pipeline_retry.py` | Task 10 |
| `purge_poisoned` 行为 | `tests/test_cache_cleaner.py` | Task 11 |

### 验收命令

```bash
pytest -q
ruff check finix_restore tests   # 若已纳入；未纳入则跳过
python -m finix_restore.cli --purge-poisoned --work_dir outputs/run_A_10
bash test.sh  # 限制 --limit 1 做冒烟，再用历史最差的 long_strip 单图复测
```

### 验收门槛

1. `pytest -q` 全绿；新增用例覆盖上表。
2. `outputs/run_A_10/logs/run.jsonl` 中 `retryable_error` 占比从 51% 下降到 ≤ 15%（在同样网络条件下相对值，需在 PR 描述中附本机复测数据）。
3. `grep -rl '<!DOCTYPE\|顾客太多\|服务器繁忙' outputs/run_A_10/api_raw outputs/run_A_10/merged` 无命中。
4. `submission_A_10.csv` 经 `pandas.read_csv` 后行数 == 输入文件数；`ground_truth` 字段长度逐行与 `merged/*.md` 长度一致。
5. 至少一个曾经 `passed=false / high_duplication` 的文件，在新分支上 `passed=true` 且 `duplication_ratio < 0.18`。
6. 现有所有原通过用例不退化。

---

## 风险与回滚

- **行级 LCS 误删风险**：保留 `long_strategy="char_match"` 与配置开关；若上线后某文件 `chars` 异常下降，配置回滚到 `char_match` 即可。
- **冷却参数过激**：`cooldown_seconds` / `max_retries` 通过 yaml 配置，非常量。
- **并发引入竞态**：`_log` 写入需加锁（`threading.Lock`）；`_next_user_id` 也需锁，单测覆盖（Task 10）。
- **CSV `QUOTE_ALL` 体积**：会变大但仍是合规 CSV；评测系统按 pandas 读取，无影响。

---

## 自检（Self-Review）

1. **Spec 覆盖**：问题文档 #1–#9 → 任务 #1/#2/#3/#5/#6/#7/#8/#9/#10/#11/#4 均一一对应；#9（绝对路径泄露）作为后置非阻断项不在本计划，README 中提示。
2. **占位符扫描**：本计划无 TODO/TBD；代码片段仅作契约示例，完整实现进入仓库。
3. **类型与命名一致**：`html_leak_markers`、`_looks_like_leak`、`html_error_leak`、`long_strategy="line_lcs"`、`purge_poisoned` 全文一致。
