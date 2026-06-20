# Pipeline Image Concurrency and API Limiter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 `Pipeline` 中加入图级并发，并用共享 API 限流器控制全局 FinixDoc-VL 请求数，提升大数据集吞吐且不突破接口稳定边界。

**Architecture:** 保持现有 `ImageProfiler -> LayoutSentry -> Chunker -> FinixApiClient -> Normalizer -> Merge -> QualityGate -> SubmissionWriter` 主链路不变。`Pipeline.run()` 负责并发调度多张图片，`FinixApiClient.parse_chunks()` 继续负责单图内 chunk 并发；新增 `ApiConcurrencyLimiter` 作为所有图片、所有 chunk 共享的请求闸门，统一限制全局并发和单 userId 并发。最终 CSV 仍按输入图片排序输出，QC 失败仍阻断正式提交。

**Tech Stack:** Python 3.12、`concurrent.futures.ThreadPoolExecutor`、`threading.BoundedSemaphore`、`requests`、Pillow、pandas、pytest、PyYAML。

---

## 0. 审核修订记录

本次审核发现并修正以下计划问题：

- 原计划把 `api.concurrency` 同时写成全局请求上限和单个 `FinixApiClient` 的 chunk worker 数，执行者容易误解。现明确：`api.concurrency` 是真实 HTTP 请求全局上限；单图 chunk worker 数由 `Pipeline._chunk_worker_concurrency()` 派生，用于避免图级并发时创建过多等待线程。
- 原计划只测试同 userId 限流，没有测试不同 userId 共享全局上限。现补充跨 userId 的 global semaphore 测试。
- 原计划没有测试 `runtime.image_concurrency < 1` 的配置错误路径。现补充失败测试和 `getattr(args, "image_concurrency", None)` 兼容要求。
- 原计划在文件清单里使用了模糊的按需修改表述，执行边界不清。现移除该模糊项，把质量门禁相关测试列为回归命令而不是改动文件。
- 原计划的 dry-run 验收输入目录漏了实际 `images/` 子目录。现改为当前仓库真实图片目录。
- 原计划的 `FinixApiClient` 线程本地 session 片段会创建一个未使用的默认共享 `requests.Session()`。现改为只保存注入的 session，未注入时按线程懒加载。

## 1. 需求来源与强约束

需求来源：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/Task2复杂金融文档还原挑战.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/FinixDoc-VL的API调用说明.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/技术方案-gpt5.5thinking/04_技术架构文档.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/技术方案-gpt5.5thinking/05_实施清单与风险控制.md`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/superpowers/plans/2026-06-18-finix-api-qc-retry-hardening.md`
- 当前源码：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore`

强约束：

- 只允许调用 FinixDoc-VL，不接入其他外部大模型或 VLM API。
- 不读取、打印或写入 `.env` 中真实密钥；日志和配置快照继续隐藏 `api_key`。
- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data` 下原始样本。
- 不按测试集文件名写特判逻辑；并发策略只能依赖配置、图片列表和现有 pipeline 状态。
- `outputs/` 仍只作为运行产物，不纳入提交。
- 并发后输出必须可复现：CSV 行集合和行顺序与串行排序一致。

非目标：

- 不重写切块算法、去重算法、表格合并算法和质量门禁规则。
- 不把 API 调用协议从 `requests` 改成 `aiohttp` 或其他异步栈。
- 不新增外部服务、队列系统、数据库或 GPU 依赖。
- 不在计划文档中展开完整实现；完整实现进入代码仓库和 PR。

## 2. 当前代码差距

当前已有能力：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
  - `FinixApiClient.parse_chunks()` 已使用 `ThreadPoolExecutor(max_workers=self.concurrency)` 并发处理单张图内 chunks。
  - `config.api.concurrency` 目前被解释为单个 `FinixApiClient` 的 chunk 并发。
  - `config.api.per_user_concurrency` 目前只用于计算 `client.concurrency` 上限，没有真正的 per-user semaphore。

当前瓶颈：

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - `Pipeline.run()` 在 `for image_path in image_paths:` 中逐图调用 `_process_image()`，必须等一张图完整完成后才处理下一张。
  - 如果直接给图片循环套线程池，`图片并发数 * 单图 chunk 并发数` 会超过预期 API 并发。

目标差距：

- 需要一个所有 `FinixApiClient` 共享的限流器，让 `api.concurrency` 表示全局 API 请求上限。
- 需要 `runtime.image_concurrency` 表示图级并发数，默认保守为 1，用户可按环境调高。
- 需要确保多线程下 userId 轮询、HTTP session、日志写入不产生竞争问题。

## 3. 文件结构与职责

### 3.1 生产代码

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/concurrency.py`
  - 定义 `ApiConcurrencyLimiter`。
  - 使用 `threading.BoundedSemaphore` 控制全局请求并发与单 userId 请求并发。
  - 提供 `acquire(user_id)` context manager。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
  - `RunConfig` 新增 `runtime` 配置，兼容现有测试中不传 `runtime` 的构造方式。
  - `load_config()` 读取 `runtime.image_concurrency`，并支持 CLI 覆盖。
  - 保持 `api.concurrency = min(requested, len(user_ids) * per_user_concurrency)` 的上限逻辑。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py`
  - 新增 `--image_concurrency` 参数。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
  - 接收共享 `ApiConcurrencyLimiter` 与共享 `log_lock`。
  - `_post_chunk()` 真实发请求前进入限流器。
  - `_next_user_id()` 用 lock 保护轮询索引。
  - 默认 HTTP session 改为线程本地 session；测试注入的 fake session 保持原样使用。
  - `_log()` 使用共享 lock 防止 JSONL 多线程交错写入。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
  - `Pipeline.__init__()` 创建一个共享 `ApiConcurrencyLimiter` 和一个共享 `threading.Lock`。
  - `Pipeline.run()` 使用图级 `ThreadPoolExecutor` 并发处理图片。
  - `_parse_chunks()` 将共享限流器和日志锁传给 `FinixApiClient`。
  - 回填 `ProcessedFile` 与 CSV rows 时保持输入排序。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
  - 新增 `runtime.image_concurrency: 1`。

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/README.md`
  - 增加图级并发和全局 API 限流说明。
  - 更新配置示例和参数表。

### 3.2 测试文件

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`

## 4. 接口契约

### 4.1 配置契约

新增配置：

```yaml
runtime:
  image_concurrency: 1
```

语义：

- `runtime.image_concurrency`: 同时处理的图片数量。默认 `1`，保持现有串行行为；A/B 榜大批量运行建议从 `2` 开始压测。
- `api.concurrency`: 全局同时调用 FinixDoc-VL 的请求数量上限，不再只是单个图片的 chunk worker 数。
- `api.per_user_concurrency`: 单个 `userId` 同时调用 FinixDoc-VL 的请求数量上限。

CLI 覆盖：

```bash
python -m finix_restore.cli \
  --input_dir data/test_images \
  --output_csv outputs/submission.csv \
  --work_dir outputs/run \
  --image_concurrency 2
```

关键断言：

```python
assert config.runtime["image_concurrency"] == 2
assert config.api["concurrency"] <= len(config.user_ids) * config.api["per_user_concurrency"]
```

### 4.2 `ApiConcurrencyLimiter` 契约

新文件：`/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/concurrency.py`

公开接口：

```python
class ApiConcurrencyLimiter:
    def __init__(self, global_concurrency: int, user_ids: Sequence[str], per_user_concurrency: int) -> None:
        ...

    @contextmanager
    def acquire(self, user_id: str) -> Iterator[None]:
        ...
```

行为要求：

- `global_concurrency < 1` 时抛出 `ValueError("global_concurrency must be >= 1")`。
- `per_user_concurrency < 1` 时抛出 `ValueError("per_user_concurrency must be >= 1")`。
- `user_ids` 为空时抛出 `ValueError("user_ids must not be empty")`。
- 未知 `user_id` 进入 `acquire()` 时抛出 `ValueError("unknown user_id: ...")`。
- `acquire(user_id)` 必须先拿对应 user semaphore，再拿 global semaphore；释放顺序反过来。

关键片段：

```python
with limiter.acquire(user_id):
    response = session.post(...)
```

### 4.3 `FinixApiClient` 契约

构造器新增可选参数：

```python
limiter: ApiConcurrencyLimiter | None = None
log_lock: threading.Lock | None = None
```

行为要求：

- 未传 `limiter` 时，客户端内部创建一个等价于当前配置的本地 limiter，保持单独使用 `FinixApiClient` 的测试和脚本兼容。
- `_next_user_id()` 在多线程 chunk worker 下安全轮询。
- `_post_chunk()` 只在进入 limiter 后发起 HTTP 请求。
- 注入 fake `session` 的测试继续使用同一个 fake session；未注入 session 时，每个线程使用自己的 `requests.Session()`。
- `_log()` 写 `logs/run.jsonl` 时必须持有 `log_lock`，避免多线程 JSON 行交错。

关键 diff：

```diff
 class FinixApiClient:
     def __init__(
         ...
+        limiter: ApiConcurrencyLimiter | None = None,
+        log_lock: threading.Lock | None = None,
     ) -> None:
         ...
+        self.limiter = limiter or ApiConcurrencyLimiter(
+            global_concurrency=self.concurrency,
+            user_ids=self.user_ids,
+            per_user_concurrency=per_user_concurrency or self.concurrency,
+        )
+        self._user_lock = threading.Lock()
+        self._log_lock = log_lock or threading.Lock()
+        self._thread_local = threading.local()
```

### 4.4 `Pipeline` 契约

行为要求：

- `image_concurrency == 1` 时，行为与当前串行版本一致。
- `image_concurrency > 1` 时，多张图片可同时执行 `_process_image()`。
- `api.concurrency` 只定义真实 HTTP 请求全局上限；每个 `FinixApiClient` 的 chunk worker 数由 `Pipeline._chunk_worker_concurrency()` 根据图级并发派生，避免 worker 线程数随图片数线性膨胀。
- `SubmissionWriter.write()` 的 rows 顺序必须与 `_list_images()` 返回顺序一致。
- 任一 `ProcessedFile.quality.passed is False` 时，正式模式仍不写 `output_csv`，并写出 `qc/summary.json`。
- 多图并发不影响 resume、dry-run、retry planner 和 per-file QC 文件写入。

关键片段：

```python
processed_files: list[ProcessedFile | None] = [None] * len(image_paths)
rows: list[dict[str, str] | None] = [None] * len(image_paths)
```

chunk worker 派生规则：

```python
def _chunk_worker_concurrency(self, concurrency_override: int | None = None) -> int:
    if concurrency_override is not None:
        return max(1, int(concurrency_override))
    global_limit = max(1, int(self.config.api.get("concurrency", 1)))
    image_concurrency = max(1, int(self.config.runtime.get("image_concurrency", 1)))
    if image_concurrency <= 1:
        return global_limit
    return max(1, min(global_limit, (global_limit + image_concurrency - 1) // image_concurrency))
```

## 5. 实施任务

### Task 1: 增加图级并发配置与 CLI 参数

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py` 增加以下测试。`_write_yaml()` 中同步加入 `runtime.image_concurrency: 3`。

```python
def test_config_reads_image_concurrency_from_runtime_yaml(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1,u2,u3")

    args = parse_args(
        [
            "--input_dir",
            str(input_dir),
            "--output_csv",
            str(tmp_path / "submission.csv"),
            "--work_dir",
            str(tmp_path / "work"),
            "--config",
            str(config_path),
        ]
    )

    config = load_config(args)

    assert config.runtime["image_concurrency"] == 3
    assert config.snapshot()["runtime"]["image_concurrency"] == 3


def test_cli_image_concurrency_overrides_runtime_yaml(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1,u2,u3")

    args = parse_args(
        [
            "--input_dir",
            str(input_dir),
            "--output_csv",
            str(tmp_path / "submission.csv"),
            "--work_dir",
            str(tmp_path / "work"),
            "--config",
            str(config_path),
            "--image_concurrency",
            "2",
        ]
    )

    config = load_config(args)

    assert config.runtime["image_concurrency"] == 2


def test_config_rejects_invalid_image_concurrency(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1")

    args = parse_args(
        [
            "--input_dir",
            str(input_dir),
            "--output_csv",
            str(tmp_path / "submission.csv"),
            "--work_dir",
            str(tmp_path / "work"),
            "--config",
            str(config_path),
            "--image_concurrency",
            "0",
        ]
    )

    with pytest.raises(ConfigError, match="runtime.image_concurrency must be >= 1"):
        load_config(args)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py::test_config_reads_image_concurrency_from_runtime_yaml \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py::test_cli_image_concurrency_overrides_runtime_yaml \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py::test_config_rejects_invalid_image_concurrency -q
```

Expected: FAIL，失败原因包含 `AttributeError` 或 `unrecognized arguments: --image_concurrency`。

- [ ] **Step 3: 实现最小配置改动**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py` 增加参数：

```diff
 parser.add_argument("--force_api", action="store_true")
 parser.add_argument("--dry_run", action="store_true")
+parser.add_argument("--image_concurrency", type=int)
```

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py` 增加 `runtime` 字段，兼容旧 fixture：

```diff
-from dataclasses import asdict, dataclass
+from dataclasses import asdict, dataclass, field
 ...
     merge: dict[str, float | int]
     quality: dict[str, float | int]
+    runtime: dict[str, int] = field(default_factory=lambda: {"image_concurrency": 1})
```

在 `load_config()` 中读取并校验：

```python
runtime = {"image_concurrency": int(raw.get("runtime", {}).get("image_concurrency", 1))}
cli_image_concurrency = getattr(args, "image_concurrency", None)
if cli_image_concurrency is not None:
    runtime["image_concurrency"] = int(cli_image_concurrency)
if runtime["image_concurrency"] < 1:
    raise ConfigError("runtime.image_concurrency must be >= 1")
```

构造 `RunConfig` 时传入：

```diff
 quality=dict(raw.get("quality", {})),
+runtime=runtime,
 resume=bool(args.resume),
```

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml` 增加：

```yaml
runtime:
  image_concurrency: 1
```

- [ ] **Step 4: 运行配置测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/config.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/cli.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py
git commit -m "feat: add image concurrency configuration"
```

### Task 2: 新增共享 API 限流器

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/concurrency.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py`

- [ ] **Step 1: 写失败测试**

创建 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py`：

```python
import threading

import pytest

from finix_restore.concurrency import ApiConcurrencyLimiter


WAIT_TIMEOUT = 2


def test_limiter_rejects_invalid_limits():
    with pytest.raises(ValueError, match="global_concurrency must be >= 1"):
        ApiConcurrencyLimiter(global_concurrency=0, user_ids=["u1"], per_user_concurrency=1)
    with pytest.raises(ValueError, match="per_user_concurrency must be >= 1"):
        ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1"], per_user_concurrency=0)
    with pytest.raises(ValueError, match="user_ids must not be empty"):
        ApiConcurrencyLimiter(global_concurrency=1, user_ids=[], per_user_concurrency=1)


def test_limiter_blocks_second_request_for_same_user_until_release():
    limiter = ApiConcurrencyLimiter(global_concurrency=2, user_ids=["u1"], per_user_concurrency=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker():
        with limiter.acquire("u1"):
            first_entered.set()
            assert release_first.wait(WAIT_TIMEOUT)

    def second_worker():
        assert first_entered.wait(WAIT_TIMEOUT)
        with limiter.acquire("u1"):
            second_entered.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    second.start()

    assert first_entered.wait(WAIT_TIMEOUT)
    assert not second_entered.wait(0.1)
    release_first.set()
    first.join(timeout=WAIT_TIMEOUT)
    second.join(timeout=WAIT_TIMEOUT)

    assert second_entered.is_set()
    assert not first.is_alive()
    assert not second.is_alive()


def test_limiter_blocks_when_global_limit_is_exhausted_across_users():
    limiter = ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1", "u2"], per_user_concurrency=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker():
        with limiter.acquire("u1"):
            first_entered.set()
            assert release_first.wait(WAIT_TIMEOUT)

    def second_worker():
        assert first_entered.wait(WAIT_TIMEOUT)
        with limiter.acquire("u2"):
            second_entered.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    second.start()

    assert first_entered.wait(WAIT_TIMEOUT)
    assert not second_entered.wait(0.1)
    release_first.set()
    first.join(timeout=WAIT_TIMEOUT)
    second.join(timeout=WAIT_TIMEOUT)

    assert second_entered.is_set()
    assert not first.is_alive()
    assert not second.is_alive()


def test_limiter_rejects_unknown_user_id():
    limiter = ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1"], per_user_concurrency=1)
    with pytest.raises(ValueError, match="unknown user_id: u2"):
        with limiter.acquire("u2"):
            pass
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py -q
```

Expected: FAIL，失败原因包含 `ModuleNotFoundError: No module named 'finix_restore.concurrency'`。

- [ ] **Step 3: 实现最小限流器**

创建 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/concurrency.py`，保留以下接口和释放顺序：

```python
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import BoundedSemaphore


class ApiConcurrencyLimiter:
    def __init__(self, global_concurrency: int, user_ids: Sequence[str], per_user_concurrency: int) -> None:
        if global_concurrency < 1:
            raise ValueError("global_concurrency must be >= 1")
        if per_user_concurrency < 1:
            raise ValueError("per_user_concurrency must be >= 1")
        if not user_ids:
            raise ValueError("user_ids must not be empty")
        self._global = BoundedSemaphore(global_concurrency)
        self._per_user = {user_id: BoundedSemaphore(per_user_concurrency) for user_id in user_ids}

    @contextmanager
    def acquire(self, user_id: str) -> Iterator[None]:
        if user_id not in self._per_user:
            raise ValueError(f"unknown user_id: {user_id}")
        user_sem = self._per_user[user_id]
        user_sem.acquire()
        self._global.acquire()
        try:
            yield
        finally:
            self._global.release()
            user_sem.release()
```

- [ ] **Step 4: 运行限流器测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/concurrency.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py
git commit -m "feat: add shared api concurrency limiter"
```

### Task 3: 将限流器接入 FinixApiClient 并修复线程竞争点

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py`

- [ ] **Step 1: 写失败测试**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py` 增加测试：

```python
from contextlib import contextmanager


def test_post_chunk_uses_limiter_around_http_request(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    class TrackingLimiter:
        def __init__(self):
            self.active = False
            self.entered_user_ids = []
            self.post_happened_inside_limiter = False

        @contextmanager
        def acquire(self, user_id):
            self.entered_user_ids.append(user_id)
            self.active = True
            try:
                yield
            finally:
                self.active = False

    class CheckingSession(FakeSession):
        def __init__(self, limiter):
            super().__init__([FakeResponse(200, "# ok")])
            self.limiter = limiter

        def post(self, url, data=None, files=None, timeout=None):
            self.limiter.post_happened_inside_limiter = self.limiter.active
            return super().post(url, data=data, files=files, timeout=timeout)

    paths = RunPaths.from_work_dir(tmp_path / "work")
    limiter = TrackingLimiter()
    session = CheckingSession(limiter)
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        limiter=limiter,
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "# ok"
    assert limiter.entered_user_ids == ["finixA1001"]
    assert limiter.post_happened_inside_limiter is True
    assert limiter.active is False
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py::test_post_chunk_uses_limiter_around_http_request -q
```

Expected: FAIL，失败原因包含 `unexpected keyword argument 'limiter'`。

- [ ] **Step 3: 实现客户端接入**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py` 增加 imports：

```diff
 import re
 import time
 from concurrent.futures import ThreadPoolExecutor
 from pathlib import Path
+import threading
 from typing import Callable
 
 import requests
 
+from finix_restore.concurrency import ApiConcurrencyLimiter
```

构造器新增参数和字段：

```diff
         run_id: str | None = None,
         session=None,
+        limiter: ApiConcurrencyLimiter | None = None,
+        log_lock: threading.Lock | None = None,
         sleep: Callable[[int], None] = time.sleep,
     ) -> None:
         ...
-        self.session = session or requests.Session()
+        self.session = session
+        self._provided_session = session
+        self._thread_local = threading.local()
         self.sleep = sleep
         self._user_index = 0
+        self._user_lock = threading.Lock()
+        self._log_lock = log_lock or threading.Lock()
+        self.limiter = limiter or ApiConcurrencyLimiter(
+            global_concurrency=self.concurrency,
+            user_ids=self.user_ids,
+            per_user_concurrency=per_user_concurrency or self.concurrency,
+        )
```

新增私有 session 获取函数，避免默认 `requests.Session()` 被多个 chunk worker 共享：

```python
def _session(self):
    if self._provided_session is not None:
        return self._provided_session
    session = getattr(self._thread_local, "session", None)
    if session is None:
        session = requests.Session()
        self._thread_local.session = session
    return session
```

保护 userId 轮询：

```diff
 def _next_user_id(self) -> str:
-    if len(self._disabled_user_ids) >= len(self.user_ids):
-        self._disabled_user_ids.clear()
-    for _ in range(len(self.user_ids)):
-        user_id = self.user_ids[self._user_index % len(self.user_ids)]
-        self._user_index += 1
-        if user_id not in self._disabled_user_ids:
-            return user_id
-    return self.user_ids[0]
+    with self._user_lock:
+        if len(self._disabled_user_ids) >= len(self.user_ids):
+            self._disabled_user_ids.clear()
+        for _ in range(len(self.user_ids)):
+            user_id = self.user_ids[self._user_index % len(self.user_ids)]
+            self._user_index += 1
+            if user_id not in self._disabled_user_ids:
+                return user_id
+        return self.user_ids[0]
```

在 `_post_chunk()` 发请求前进入 limiter：

```diff
 try:
     with chunk.image_path.open("rb") as f:
         files = {"file": (chunk.image_path.name, f)}
-        response = self.session.post(
-            self.api_url,
-            data=data,
-            files=files,
-            timeout=self.timeout_seconds,
-        )
+        with self.limiter.acquire(user_id):
+            response = self._session().post(
+                self.api_url,
+                data=data,
+                files=files,
+                timeout=self.timeout_seconds,
+            )
```

保护 JSONL 写入：

```diff
 def _log(self, payload: dict[str, object]) -> None:
     self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
-    with (self.paths.logs_dir / "run.jsonl").open("a", encoding="utf-8") as f:
-        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
+    with self._log_lock:
+        with (self.paths.logs_dir / "run.jsonl").open("a", encoding="utf-8") as f:
+            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 运行 API 测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/finix_api.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py
git commit -m "feat: limit finix api calls across threads"
```

### Task 4: Pipeline.run 支持图级并发且保持输出顺序

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py`

- [ ] **Step 1: 写图级并发和排序测试**

创建 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py`：

```python
import threading

import pandas as pd
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.models import ProcessedFile, QualityReport
from finix_restore.paths import RunPaths


WAIT_TIMEOUT = 2


def _config(tmp_path, input_dirs, image_concurrency=2):
    return RunConfig(
        input_dirs=input_dirs,
        output_csv=tmp_path / "submission.csv",
        paths=RunPaths.from_work_dir(tmp_path / "work"),
        api_key="secret",
        user_ids=["u1", "u2"],
        api_url="https://example.test/api",
        api={"timeout_seconds": 1, "max_retries": 0, "concurrency": 2, "per_user_concurrency": 1},
        chunk={
            "max_chunk_pixels": 12_000_000,
            "table_full_page_max_pixels": 16_000_000,
            "long_window_height": 4000,
            "long_vertical_overlap": 320,
            "table_horizontal_overlap": 160,
            "table_vertical_overlap": 220,
        },
        merge={"dedup_similarity_threshold": 0.88},
        quality={"max_duplication_ratio": 0.18, "max_api_failure_ratio": 0.20, "max_reruns_per_file": 1},
        runtime={"image_concurrency": image_concurrency},
    )


def test_pipeline_processes_images_concurrently_but_writes_csv_in_input_order(tmp_path, monkeypatch):
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "a.png")
    Image.new("RGB", (120, 240), "white").save(input_dir / "b.png")

    a_started = threading.Event()
    b_started = threading.Event()
    release_a = threading.Event()

    def fake_process_image(self, image_path):
        if image_path.name == "a.png":
            a_started.set()
            assert b_started.wait(WAIT_TIMEOUT)
            assert release_a.wait(WAIT_TIMEOUT)
            return ProcessedFile(
                file_name="a.png",
                markdown="A",
                quality=QualityReport(True, [], {"doc_type": "normal_page"}),
            )
        assert a_started.wait(WAIT_TIMEOUT)
        b_started.set()
        release_a.set()
        return ProcessedFile(
            file_name="b.png",
            markdown="B",
            quality=QualityReport(True, [], {"doc_type": "normal_page"}),
        )

    monkeypatch.setattr(Pipeline, "_process_image", fake_process_image)
    config = _config(tmp_path, [input_dir], image_concurrency=2)

    report = Pipeline(config).run()

    df = pd.read_csv(config.output_csv)
    assert report.passed
    assert list(df["file_name"]) == ["a.png", "b.png"]
    assert list(df["ground_truth"]) == ["A", "B"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py::test_pipeline_processes_images_concurrently_but_writes_csv_in_input_order -q
```

Expected: FAIL，失败原因是 `b_started.wait(WAIT_TIMEOUT)` 断言失败，说明当前 `Pipeline.run()` 仍串行。

- [ ] **Step 3: 实现 Pipeline 图级并发**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py` 增加 imports：

```diff
 import json
+import threading
 import uuid
+from concurrent.futures import ThreadPoolExecutor, as_completed
```

在 `Pipeline.__init__()` 中创建共享对象：

```python
self.api_limiter = ApiConcurrencyLimiter(
    global_concurrency=int(config.api.get("concurrency", 1)),
    user_ids=config.user_ids,
    per_user_concurrency=int(config.api.get("per_user_concurrency", 1)),
)
self.log_lock = threading.Lock()
```

同步 import：

```python
from finix_restore.concurrency import ApiConcurrencyLimiter
```

新增 chunk worker 派生方法：

```python
def _chunk_worker_concurrency(self, concurrency_override: int | None = None) -> int:
    if concurrency_override is not None:
        return max(1, int(concurrency_override))
    global_limit = max(1, int(self.config.api.get("concurrency", 1)))
    image_concurrency = max(1, int(self.config.runtime.get("image_concurrency", 1)))
    if image_concurrency <= 1:
        return global_limit
    return max(1, min(global_limit, (global_limit + image_concurrency - 1) // image_concurrency))
```

将 `run()` 中的逐图循环替换为按下标回填的并发调度。保留串行 fallback，方便排查问题：

```python
image_concurrency = int(self.config.runtime.get("image_concurrency", 1))
processed_files: list[ProcessedFile | None] = [None] * len(image_paths)
rows: list[dict[str, str] | None] = [None] * len(image_paths)

if image_concurrency <= 1:
    for index, image_path in enumerate(image_paths):
        processed = self._process_image(image_path)
        processed_files[index] = processed
        rows[index] = {"file_name": image_path.name, "ground_truth": processed.markdown}
else:
    with ThreadPoolExecutor(max_workers=image_concurrency) as executor:
        future_to_index = {
            executor.submit(self._process_image, image_path): index
            for index, image_path in enumerate(image_paths)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            image_path = image_paths[index]
            processed = future.result()
            processed_files[index] = processed
            rows[index] = {"file_name": image_path.name, "ground_truth": processed.markdown}

if any(item is None for item in processed_files) or any(item is None for item in rows):
    raise PipelineError("internal error: incomplete parallel image results")
final_processed = [item for item in processed_files if item is not None]
final_rows = [item for item in rows if item is not None]
```

后续 summary 和 submission 使用 `final_processed`、`final_rows`。

- [ ] **Step 4: 运行图级并发测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py::test_pipeline_processes_images_concurrently_but_writes_csv_in_input_order -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py
git commit -m "feat: process images concurrently in pipeline"
```

### Task 5: Pipeline 将共享限流器传给所有 FinixApiClient

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py`

- [ ] **Step 1: 写失败测试**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py` 增加：

```python
def test_pipeline_passes_shared_limiter_and_log_lock_to_finix_clients(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "a.png")
    Image.new("RGB", (120, 240), "white").save(input_dir / "b.png")

    captured_limiters = []
    captured_log_locks = []

    class CapturingClient:
        def __init__(self, **kwargs):
            captured_limiters.append(kwargs["limiter"])
            captured_log_locks.append(kwargs["log_lock"])

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(chunk=chunk, markdown="# ok", block_type="body", source="api")
                for chunk in chunks
            ], 0

    config = _config(tmp_path, [input_dir], image_concurrency=2)
    pipeline = Pipeline(config)
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", CapturingClient)

    report = pipeline.run()

    assert report.passed
    assert captured_limiters
    assert all(limiter is pipeline.api_limiter for limiter in captured_limiters)
    assert captured_log_locks
    assert all(lock is pipeline.log_lock for lock in captured_log_locks)


def test_pipeline_scales_chunk_worker_count_when_image_concurrency_is_enabled(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "a.png")
    Image.new("RGB", (120, 240), "white").save(input_dir / "b.png")

    captured_concurrency = []

    class CapturingClient:
        def __init__(self, **kwargs):
            captured_concurrency.append(kwargs["concurrency"])

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(chunk=chunk, markdown="# ok", block_type="body", source="api")
                for chunk in chunks
            ], 0

    config = _config(tmp_path, [input_dir], image_concurrency=2)
    config.api["concurrency"] = 4
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", CapturingClient)

    report = Pipeline(config).run()

    assert report.passed
    assert captured_concurrency
    assert set(captured_concurrency) == {2}
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py::test_pipeline_passes_shared_limiter_and_log_lock_to_finix_clients \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py::test_pipeline_scales_chunk_worker_count_when_image_concurrency_is_enabled -q
```

Expected: FAIL，第一个测试失败原因包含 `KeyError: 'limiter'`，第二个测试在未使用 `_chunk_worker_concurrency()` 前会捕获到 `{4}`。

- [ ] **Step 3: 在 _parse_chunks() 使用派生 worker 数并传入共享对象**

修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py` 中 `FinixApiClient(...)` 构造参数：

```diff
+worker_concurrency = self._chunk_worker_concurrency(concurrency_override)
 client = FinixApiClient(
     api_key=self.config.api_key,
     user_ids=self.config.user_ids,
     api_url=self.config.api_url,
     paths=self.config.paths,
     timeout_seconds=int(self.config.api.get("timeout_seconds", 240)),
     max_retries=int(self.config.api.get("max_retries", 3)),
-    concurrency=concurrency_override or int(self.config.api.get("concurrency", 1)),
+    concurrency=worker_concurrency,
     per_user_concurrency=int(self.config.api.get("per_user_concurrency", 1)),
     run_id=self.run_id,
+    limiter=self.api_limiter,
+    log_lock=self.log_lock,
 )
```

- [ ] **Step 4: 运行 Pipeline 并发测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py -q
```

Expected: PASS。

- [ ] **Step 5: 回归质量门禁相关测试**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/finix_restore/pipeline.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py
git commit -m "feat: share api limiter across image workers"
```

### Task 6: 文档、dry-run 验收与全量测试

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/README.md`
- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/reproduce.md`

- [ ] **Step 1: 更新 README 配置示例**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/README.md` 的配置示例中加入：

```yaml
runtime:
  image_concurrency: 2
```

在参数表加入：

```markdown
| `--image_concurrency` | 同时处理的图片数量；API 总请求并发仍由 `api.concurrency` 统一限制 | 配置文件中的 `runtime.image_concurrency` |
```

在 API 配置说明中加入：

```markdown
`api.concurrency` 表示全局 FinixDoc-VL 请求上限，`api.per_user_concurrency` 表示单个 userId 的请求上限。建议先使用 `image_concurrency=2`、`api.concurrency=4`、`per_user_concurrency=1` 压测，确认无超时或服务繁忙后再调高。
```

- [ ] **Step 2: 更新复现文档**

在 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/reproduce.md` 的 A 榜运行命令后增加“并发参数建议”小节：

```markdown
并发参数建议：

- `runtime.image_concurrency` 控制同时处理的图片数量。
- `api.concurrency` 控制全局 FinixDoc-VL 请求数量上限。
- `api.per_user_concurrency` 控制单个 userId 的请求数量上限。

保守起步建议使用 `image_concurrency=2`、`api.concurrency=4`、`per_user_concurrency=1`。如果 `qc/summary.json` 中出现 `service_busy_html`、`api_failure_ratio_high` 或超时增多，先把 `image_concurrency` 降回 1，再降低 `api.concurrency`。
```

- [ ] **Step 3: 运行帮助输出检查**

Run:

```bash
python -m finix_restore.cli --help | rg -- '--image_concurrency'
```

Expected: 输出包含 `--image_concurrency IMAGE_CONCURRENCY`。

- [ ] **Step 4: 运行 targeted tests**

Run:

```bash
pytest /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_config.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_concurrency.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_finix_api.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_parallel.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_pipeline_quality_blocking.py \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_submission.py -q
```

Expected: PASS。

- [ ] **Step 5: 运行全量测试和 diff 检查**

Run:

```bash
pytest -q
git diff --check
```

Expected: 两条命令均通过；`pytest -q` 无失败测试，`git diff --check` 无 whitespace error。

- [ ] **Step 6: 运行 dry-run 验收**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --input_dir "/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  --output_csv /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/parallel_dry_run/submission.csv \
  --work_dir /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/parallel_dry_run \
  --config /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/configs/default.yaml \
  --limit_per_dir 1 \
  --image_concurrency 2 \
  --dry_run
```

Expected:

- 命令完成且不调用真实 API。
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/parallel_dry_run/submission.csv` 可被 pandas 读取。
- CSV 列名为 `file_name,ground_truth`。
- CSV 行数为 `2`。
- `qc/summary.json` 中 `dry_run` 为 `true`。

检查命令：

```bash
python - <<'PY'
import json
import pandas as pd
from pathlib import Path

base = Path("/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/parallel_dry_run")
df = pd.read_csv(base / "submission.csv")
summary = json.loads((base / "qc" / "summary.json").read_text(encoding="utf-8"))
assert list(df.columns) == ["file_name", "ground_truth"]
assert len(df) == 2
assert not df["file_name"].duplicated().any()
assert summary["dry_run"] is True
print("parallel dry-run csv ok")
PY
```

Expected: 输出 `parallel dry-run csv ok`。

- [ ] **Step 7: 提交**

```bash
git add /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/README.md \
  /Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/reproduce.md
git commit -m "docs: document image concurrency controls"
```

## 6. 最终验收清单

功能验收：

- `Pipeline.run()` 支持 `runtime.image_concurrency > 1` 并发处理多张图片。
- `FinixApiClient.parse_chunks()` 仍支持单图内 chunk 并发。
- 所有图片 worker 共享同一个 `ApiConcurrencyLimiter`。
- 任意时刻真实 FinixDoc-VL 请求数不超过 `api.concurrency`。
- 任意单个 `userId` 真实请求数不超过 `api.per_user_concurrency`。
- 输出 CSV 行顺序与 `_list_images()` 的排序一致。
- QC 失败仍阻断正式提交，不会留下旧 CSV。
- resume、dry-run、retry planner 行为保持兼容。

安全与合规验收：

- 不引入 FinixDoc-VL 之外的大模型或外部 VLM API。
- `run.jsonl`、`config_snapshot.yaml`、测试输出不包含真实 `apiKey`。
- 不修改 `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data`。
- 不新增按文件名特判逻辑。

测试验收：

```bash
pytest -q
git diff --check
```

提交格式验收：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

csv_path = Path("/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/parallel_dry_run/submission.csv")
df = pd.read_csv(csv_path)
assert list(df.columns) == ["file_name", "ground_truth"]
assert not df["file_name"].duplicated().any()
print(len(df))
PY
```

## 7. 建议运行参数

保守起步：

```yaml
runtime:
  image_concurrency: 2
api:
  concurrency: 4
  per_user_concurrency: 1
```

如果 5 个 userId 都稳定：

```yaml
runtime:
  image_concurrency: 3
api:
  concurrency: 5
  per_user_concurrency: 1
```

如果出现 `service_busy_html`、超时率升高或 `api_failure_ratio_high`：

```yaml
runtime:
  image_concurrency: 1
api:
  concurrency: 2
  per_user_concurrency: 1
```

## 8. 自审记录

Spec coverage:

- 图级并发：Task 4。
- 共享 API 限流：Task 2、Task 3、Task 5。
- chunk worker 派生与全局请求上限分离：第 4.4 节、Task 4、Task 5。
- 输出顺序稳定：Task 4 测试断言 CSV 顺序。
- 配置与 CLI：Task 1。
- 测试与验收：Task 1-6 和最终验收清单。
- 强约束：第 1 节、第 6 节。

Placeholder scan:

- 本计划没有使用占位式任务描述。
- 所有新增接口都有明确文件路径、测试断言和运行命令。

Type consistency:

- `RunConfig.runtime`、`ApiConcurrencyLimiter.acquire()`、`FinixApiClient(limiter=..., log_lock=...)`、`Pipeline.api_limiter`、`Pipeline._chunk_worker_concurrency()` 在任务之间命名一致。
- `api.concurrency` 在计划中统一解释为真实 HTTP 请求全局上限；单图 chunk worker 数由 `_chunk_worker_concurrency()` 派生，重跑时仍可用 `concurrency_override` 降低到 1。
