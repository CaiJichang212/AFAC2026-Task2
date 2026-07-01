from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Callable

import requests

from finix_restore.concurrency import ApiConcurrencyLimiter
from finix_restore.models import Chunk, ChunkText
from finix_restore.paths import RunPaths


class FinixApiError(RuntimeError):
    """Retryable/non-retryable API error carrying structured diagnostic fields.

    kind 枚举:
      - network_timeout / network_error : requests 层异常
      - http_5xx / http_4xx            : 服务端返回非 2xx
      - empty_response                 : 2xx 但正文为空
      - service_busy_html              : 支付宝繁忙 HTML 页
      - full_html_page                 : 完整 HTML 页 (非 markdown)
      - api_error                      : success=false 携带 message
      - auth_error                     : 401/403
      - unknown                        : 兜底
    detail 存放真实错误短文本, 便于在 run.jsonl 定位问题, 不含密钥。
    response_snippet 保留响应正文的前 N 字符 (脱敏)。
    """

    def __init__(self, message: str, *, kind: str = "unknown", detail: str = "", response_snippet: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail
        self.response_snippet = response_snippet


_CACHE_VALIDATOR_VERSION = 1
_SERVICE_BUSY_HTML_MARKERS = (
    "服务器繁忙",
    "顾客太多",
    "j_retry_link",
    "showtextwait",
    "支付宝版权所有",
)
# 单 userId 连续失败达到该阈值即进入短暂冷却, 避免限流/账号异常持续拖慢整体。
_USER_FAILURE_THRESHOLD = 3
_USER_COOLDOWN_SECONDS = 30.0
_RESPONSE_SNIPPET_MAX = 400
_DETAIL_MAX = 500


class FinixApiClient:
    def __init__(
        self,
        api_key: str,
        user_ids: list[str],
        api_url: str,
        paths: RunPaths,
        timeout_seconds: int = 240,
        max_retries: int = 3,
        concurrency: int = 4,
        per_user_concurrency: int | None = None,
        run_id: str | None = None,
        session=None,
        limiter: ApiConcurrencyLimiter | None = None,
        log_lock: threading.Lock | None = None,
        sleep: Callable[[int], None] = time.sleep,
    ) -> None:
        if not user_ids:
            raise FinixApiError("at least one userId is required", kind="config_error")
        self.api_key = api_key
        self.user_ids = list(user_ids)
        self.api_url = api_url
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        if per_user_concurrency is None:
            self.concurrency = max(1, concurrency)
        else:
            self.concurrency = min(concurrency, max(1, len(user_ids) * per_user_concurrency))
        self.per_user_concurrency = per_user_concurrency
        self.run_id = run_id or ""
        self.session = session  # 保留 attribute 兼容旧引用（含测试中的 client.session）
        self._provided_session = session
        self._thread_local = threading.local()
        self.sleep = sleep
        self._user_index = 0
        self._disabled_user_ids: set[str] = set()
        self._user_lock = threading.Lock()
        self._log_lock = log_lock or threading.Lock()
        # userId 熔断状态: 连续失败计数 + 冷却截止时间
        self._user_failure_counts: dict[str, int] = {u: 0 for u in self.user_ids}
        self._user_cooldown_until: dict[str, float] = {u: 0.0 for u in self.user_ids}
        # Safety timeout per-chunk future.result() to prevent indefinite hang
        # when requests timeout fails to trigger. Covers worst-case
        # (timeout * retries + backoff) with generous headroom.
        self._chunk_result_timeout = float(timeout_seconds) * (max_retries + 2)
        self.limiter = limiter or ApiConcurrencyLimiter(
            global_concurrency=self.concurrency,
            user_ids=self.user_ids,
            per_user_concurrency=per_user_concurrency or self.concurrency,
        )

    def parse_chunk(self, chunk: Chunk, force_api: bool = False) -> ChunkText:
        cached = None if force_api else self._read_cache(chunk)
        if cached is not None:
            cached_sha1 = self._sha1(cached)
            self._log(
                {
                    "event": "api_call",
                    "run_id": self.run_id,
                    "file_name": chunk.file_name,
                    "chunk_id": chunk.chunk_id,
                    "user_id": "",
                    "status": "cache",
                    "error_kind": "",
                    "error_detail": "",
                    "response_snippet": "",
                    "elapsed_ms": 0,
                    "retry_index": 0,
                    "response_sha1": cached_sha1,
                    "response_chars": len(cached),
                    "content_validated": True,
                }
            )
            return ChunkText(chunk=chunk, markdown=cached, block_type=self._block_type(cached), source="cache")

        last_error = "empty response"
        last_kind = "unknown"
        for retry_index in range(self.max_retries + 1):
            user_id = self._next_user_id()
            started = time.perf_counter()
            try:
                markdown = self._post_chunk(chunk, user_id)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._write_cache(chunk, markdown)
                self._record_user_success(user_id)
                self._log_api_call(chunk, user_id, "ok", elapsed_ms, retry_index, markdown)
                return ChunkText(chunk=chunk, markdown=markdown, block_type=self._block_type(markdown), source="api")
            except FinixApiError as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                last_error = str(exc)
                last_kind = exc.kind or "unknown"
                if exc.kind == "auth_error":
                    self._log_api_call(
                        chunk,
                        user_id,
                        "auth_error",
                        elapsed_ms,
                        retry_index,
                        None,
                        error_kind=exc.kind,
                        error_detail=exc.detail,
                        response_snippet=exc.response_snippet,
                    )
                    raise
                self._record_user_failure(user_id)
                # status 直接落地真实错误类别, 便于日志分析定位。
                self._log_api_call(
                    chunk,
                    user_id,
                    exc.kind or "retryable_error",
                    elapsed_ms,
                    retry_index,
                    None,
                    error_kind=exc.kind or "unknown",
                    error_detail=exc.detail,
                    response_snippet=exc.response_snippet,
                )
                if retry_index >= self.max_retries:
                    break
                self.sleep(self._backoff_seconds(retry_index, kind=exc.kind))
        raise FinixApiError(
            f"FinixDoc-VL request failed after retries [{last_kind}]: {last_error}",
            kind=last_kind,
            detail=last_error[:_DETAIL_MAX],
        )

    def parse_chunks(self, chunks: list[Chunk], force_api: bool = False) -> tuple[list[ChunkText], int]:
        def _parse_one(chunk: Chunk) -> ChunkText:
            return self.parse_chunk(chunk, force_api=force_api)

        failed_chunks = 0
        results: list[ChunkText | None] = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(_parse_one, chunk) for chunk in chunks]
            for index, future in enumerate(futures):
                chunk = chunks[index]
                try:
                    results[index] = future.result(timeout=self._chunk_result_timeout)
                except FutureTimeoutError:
                    failed_chunks += 1
                    results[index] = ChunkText(
                        chunk=chunk,
                        markdown="",
                        block_type="unknown",
                        source="api",
                    )
                    self._log(
                        {
                            "event": "chunk_timeout",
                            "run_id": self.run_id,
                            "file_name": chunk.file_name,
                            "chunk_id": chunk.chunk_id,
                            "timeout_seconds": self._chunk_result_timeout,
                        }
                    )
                except FinixApiError as exc:
                    if exc.kind == "auth_error":
                        raise
                    failed_chunks += 1
                    results[index] = ChunkText(
                        chunk=chunk,
                        markdown="",
                        block_type="unknown",
                        source="api",
                    )
        return [result for result in results if result is not None], failed_chunks

    def _post_chunk(self, chunk: Chunk, user_id: str) -> str:
        data = {
            "userId": user_id,
            "apiKey": self.api_key,
            "fileName": chunk.image_path.name,
        }
        # 显式发送空 Expect 头, 避免部分网关/代理对 Expect: 100-continue 的等待导致上传变慢。
        headers = {"Expect": ""}
        try:
            with chunk.image_path.open("rb") as f:
                files = {"file": (chunk.image_path.name, f)}
                with self.limiter.acquire(user_id):
                    response = self._session().post(
                        self.api_url,
                        data=data,
                        files=files,
                        headers=headers,
                        timeout=self.timeout_seconds,
                    )
        except requests.Timeout as exc:
            raise FinixApiError(
                f"retryable network timeout: {exc}",
                kind="network_timeout",
                detail=repr(exc)[:_DETAIL_MAX],
            ) from exc
        except requests.RequestException as exc:
            raise FinixApiError(
                f"retryable network error: {exc}",
                kind="network_error",
                detail=repr(exc)[:_DETAIL_MAX],
            ) from exc

        status_code = int(getattr(response, "status_code", 0))
        text = getattr(response, "text", "")
        snippet = self._response_snippet(str(text))
        if status_code in {401, 403}:
            raise FinixApiError(
                "authentication failed; check FINIX_USER_IDS or FINIX_API_KEY",
                kind="auth_error",
                detail=f"http {status_code}",
                response_snippet=snippet,
            )
        if status_code >= 500:
            raise FinixApiError(
                f"retryable http {status_code}",
                kind="http_5xx",
                detail=f"http {status_code}",
                response_snippet=snippet,
            )
        if status_code >= 400:
            raise FinixApiError(
                f"http {status_code}: {text[:200]}",
                kind="http_4xx",
                detail=f"http {status_code}",
                response_snippet=snippet,
            )
        markdown = self._extract_markdown(str(text))
        self._validate_markdown_response(markdown, snippet=snippet)
        if not markdown:
            raise FinixApiError(
                "empty response",
                kind="empty_response",
                detail=f"chars={len(text)}",
                response_snippet=snippet,
            )
        return markdown

    def _extract_markdown(self, response_text: str) -> str:
        text = response_text.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return self._strip_markdown_fence(text)

        if isinstance(payload, dict):
            if payload.get("success") is False:
                message = payload.get("message") or payload.get("error") or "api returned success=false"
                raise FinixApiError(
                    f"api error: {message}",
                    kind="api_error",
                    detail=str(message)[:_DETAIL_MAX],
                    response_snippet=self._response_snippet(text),
                )
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("result"), str):
                return self._extract_markdown(result["result"])
            if isinstance(result, str):
                return self._extract_markdown(result)
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return self._strip_markdown_fence(message["content"].strip())
        return self._strip_markdown_fence(text)

    def _strip_markdown_fence(self, text: str) -> str:
        stripped = text.strip()
        match = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*?)\n?```", stripped, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return stripped

    def _backoff_seconds(self, retry_index: int, kind: str | None = None) -> float:
        """按错误类别分档退避, 避免所有失败都套用同一长退避拖慢重试。

        - network_timeout / network_error: 已经等过一次超时, 无需再叠加长退避 -> 短。
        - empty_response: 服务端可能瞬时抖动, 短退避即可。
        - service_busy_html / full_html_page: 限流/繁忙 -> 长退避 + 抖动降低同步风暴。
        - 其余 (含 http_5xx / api_error): 走默认 5*2^n 递增。
        """
        if kind in ("network_timeout", "network_error"):
            base = min(2.0 * (2 ** retry_index), 10.0)
        elif kind == "empty_response":
            base = min(1.5 * (2 ** retry_index), 6.0)
        elif kind in ("service_busy_html", "full_html_page"):
            base = min(10.0 * (2 ** retry_index), 60.0)
        else:
            # API 存在连接级限流, 连续失败需要更长退避 + 抖动, 避免再次触发 RemoteDisconnected/SSLError。
            base = min(5.0 * (2 ** retry_index), 40.0)
        jitter = random.uniform(0.0, base * 0.5)
        return base + jitter

    def _next_user_id(self) -> str:
        with self._user_lock:
            if len(self._disabled_user_ids) >= len(self.user_ids):
                self._disabled_user_ids.clear()
            now = time.monotonic()
            for _ in range(len(self.user_ids)):
                user_id = self.user_ids[self._user_index % len(self.user_ids)]
                self._user_index += 1
                if user_id in self._disabled_user_ids:
                    continue
                if self._user_cooldown_until.get(user_id, 0.0) > now:
                    continue
                return user_id
            # 全部处于冷却时, 选剩余冷却时间最短的 userId, 至少继续跑
            fallback = min(self.user_ids, key=lambda u: self._user_cooldown_until.get(u, 0.0))
            return fallback

    def _record_user_failure(self, user_id: str) -> None:
        with self._user_lock:
            self._user_failure_counts[user_id] = self._user_failure_counts.get(user_id, 0) + 1
            if self._user_failure_counts[user_id] >= _USER_FAILURE_THRESHOLD:
                self._user_cooldown_until[user_id] = time.monotonic() + _USER_COOLDOWN_SECONDS
                self._user_failure_counts[user_id] = 0

    def _record_user_success(self, user_id: str) -> None:
        with self._user_lock:
            self._user_failure_counts[user_id] = 0
            self._user_cooldown_until[user_id] = 0.0

    def _session(self):
        if self._provided_session is not None:
            return self._provided_session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._thread_local.session = session
        return session

    def _raw_dir(self, chunk: Chunk) -> Path:
        return self.paths.api_raw_dir / Path(chunk.file_name).stem

    def _raw_path(self, chunk: Chunk) -> Path:
        return self._raw_dir(chunk) / f"{chunk.chunk_id}.md"

    def _meta_path(self, chunk: Chunk) -> Path:
        return self._raw_dir(chunk) / f"{chunk.chunk_id}.json"

    def _read_cache(self, chunk: Chunk) -> str | None:
        raw_path = self._raw_path(chunk)
        meta_path = self._meta_path(chunk)
        if not raw_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        raw_markdown = raw_path.read_text(encoding="utf-8")
        if meta.get("chunk_id") != chunk.chunk_id:
            return None
        if meta.get("image_sha1") != chunk.image_sha1:
            return None
        if meta.get("api_url") != self.api_url:
            return None
        if meta.get("content_validated") is not True:
            return None
        if meta.get("validator_version") != _CACHE_VALIDATOR_VERSION:
            return None
        if meta.get("response_sha1") != self._sha1(raw_markdown):
            return None
        return raw_markdown

    def _write_cache(self, chunk: Chunk, markdown: str) -> None:
        raw_dir = self._raw_dir(chunk)
        raw_dir.mkdir(parents=True, exist_ok=True)
        self._raw_path(chunk).write_text(markdown, encoding="utf-8")
        self._meta_path(chunk).write_text(
            json.dumps(
                {
                    "chunk_id": chunk.chunk_id,
                    "image_sha1": chunk.image_sha1,
                    "api_url": self.api_url,
                    "content_validated": True,
                    "validator_version": _CACHE_VALIDATOR_VERSION,
                    "response_sha1": self._sha1(markdown),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _log_api_call(
        self,
        chunk: Chunk,
        user_id: str,
        status: str,
        elapsed_ms: int,
        retry_index: int,
        markdown: str | None,
        error_kind: str = "",
        error_detail: str = "",
        response_snippet: str = "",
    ) -> None:
        self._log(
            {
                "event": "api_call",
                "run_id": self.run_id,
                "file_name": chunk.file_name,
                "chunk_id": chunk.chunk_id,
                "user_id": "***",
                "status": status,
                "error_kind": error_kind,
                "error_detail": (error_detail or "")[:_DETAIL_MAX],
                "response_snippet": (response_snippet or "")[:_RESPONSE_SNIPPET_MAX],
                "elapsed_ms": elapsed_ms,
                "retry_index": retry_index,
                "response_sha1": self._sha1(markdown) if markdown is not None else "",
                "response_chars": len(markdown) if markdown is not None else 0,
                "content_validated": markdown is not None,
            }
        )

    def _log(self, payload: dict[str, object]) -> None:
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            with (self.paths.logs_dir / "run.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _block_type(self, markdown: str) -> str:
        return "table" if "<table" in markdown.lower() else "body"

    def _validate_markdown_response(self, markdown: str, snippet: str = "") -> None:
        lowered = markdown.strip().lower()
        if not lowered:
            return
        if any(marker in lowered for marker in _SERVICE_BUSY_HTML_MARKERS):
            raise FinixApiError(
                "service busy html page",
                kind="service_busy_html",
                detail="alipay busy page markers matched",
                response_snippet=snippet,
            )
        if "alipayobjects.com" in lowered and "<html" in lowered:
            raise FinixApiError(
                "service busy html page",
                kind="service_busy_html",
                detail="alipayobjects html detected",
                response_snippet=snippet,
            )
        is_full_html = (
            (lowered.startswith("<!doctype html") or lowered.startswith("<html"))
            and "<head" in lowered
            and "<body" in lowered
        )
        if not is_full_html:
            return
        raise FinixApiError(
            "full html page response",
            kind="full_html_page",
            detail="full html doc returned",
            response_snippet=snippet,
        )

    def _response_snippet(self, text: str) -> str:
        # 只截前 N 字符, 用于日志脱敏诊断; 不会打印上传数据。
        return (text or "").strip().replace("\n", " ")[:_RESPONSE_SNIPPET_MAX]

    def _sha1(self, markdown: str | None) -> str:
        return hashlib.sha1((markdown or "").encode("utf-8")).hexdigest()
