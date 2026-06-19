from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import requests

from finix_restore.models import Chunk, ChunkText
from finix_restore.paths import RunPaths


class FinixApiError(RuntimeError):
    pass


_CACHE_VALIDATOR_VERSION = 1
_SERVICE_BUSY_HTML_MARKERS = (
    "服务器繁忙",
    "顾客太多",
    "j_retry_link",
    "showtextwait",
    "支付宝版权所有",
)


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
        sleep: Callable[[int], None] = time.sleep,
    ) -> None:
        if not user_ids:
            raise FinixApiError("at least one userId is required")
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
        self.session = session or requests.Session()
        self.sleep = sleep
        self._user_index = 0
        self._disabled_user_ids: set[str] = set()

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
                    "elapsed_ms": 0,
                    "retry_index": 0,
                    "response_sha1": cached_sha1,
                    "response_chars": len(cached),
                    "content_validated": True,
                }
            )
            return ChunkText(chunk=chunk, markdown=cached, block_type=self._block_type(cached), source="cache")

        last_error = "empty response"
        for retry_index in range(self.max_retries + 1):
            user_id = self._next_user_id()
            started = time.perf_counter()
            try:
                markdown = self._post_chunk(chunk, user_id)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._write_cache(chunk, markdown)
                self._log_api_call(chunk, user_id, "ok", elapsed_ms, retry_index, markdown)
                return ChunkText(chunk=chunk, markdown=markdown, block_type=self._block_type(markdown), source="api")
            except FinixApiError as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                last_error = str(exc)
                if "authentication" in last_error:
                    self._log_api_call(chunk, user_id, "auth_error", elapsed_ms, retry_index, None)
                    raise
                self._log_api_call(chunk, user_id, "retryable_error", elapsed_ms, retry_index, None)
                if retry_index >= self.max_retries:
                    break
                self.sleep(2**retry_index)
        raise FinixApiError(f"FinixDoc-VL request failed after retries: {last_error}")

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
                    results[index] = future.result()
                except FinixApiError as exc:
                    if "authentication" in str(exc):
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
        try:
            with chunk.image_path.open("rb") as f:
                files = {"file": (chunk.image_path.name, f)}
                response = self.session.post(
                    self.api_url,
                    data=data,
                    files=files,
                    timeout=self.timeout_seconds,
                )
        except (requests.Timeout, requests.RequestException) as exc:
            raise FinixApiError(f"retryable network error: {exc}") from exc

        status_code = int(getattr(response, "status_code", 0))
        text = getattr(response, "text", "")
        if status_code in {401, 403}:
            raise FinixApiError("authentication failed; check FINIX_USER_IDS or FINIX_API_KEY")
        if status_code >= 500:
            raise FinixApiError(f"retryable http {status_code}")
        if status_code >= 400:
            raise FinixApiError(f"http {status_code}: {text[:200]}")
        markdown = self._extract_markdown(str(text))
        self._validate_markdown_response(markdown)
        if not markdown:
            raise FinixApiError("empty response")
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
                raise FinixApiError(f"api error: {message}")
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

    def _next_user_id(self) -> str:
        if len(self._disabled_user_ids) >= len(self.user_ids):
            self._disabled_user_ids.clear()
        for _ in range(len(self.user_ids)):
            user_id = self.user_ids[self._user_index % len(self.user_ids)]
            self._user_index += 1
            if user_id not in self._disabled_user_ids:
                return user_id
        return self.user_ids[0]

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
    ) -> None:
        self._log(
            {
                "event": "api_call",
                "run_id": self.run_id,
                "file_name": chunk.file_name,
                "chunk_id": chunk.chunk_id,
                "user_id": user_id,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "retry_index": retry_index,
                "response_sha1": self._sha1(markdown) if markdown is not None else "",
                "response_chars": len(markdown) if markdown is not None else 0,
                "content_validated": markdown is not None,
            }
        )

    def _log(self, payload: dict[str, object]) -> None:
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.paths.logs_dir / "run.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _block_type(self, markdown: str) -> str:
        return "table" if "<table" in markdown.lower() else "body"

    def _validate_markdown_response(self, markdown: str) -> None:
        lowered = markdown.strip().lower()
        if not lowered:
            return
        is_full_html = (
            (lowered.startswith("<!doctype html") or lowered.startswith("<html"))
            and "<head" in lowered
            and "<body" in lowered
        )
        if not is_full_html:
            return
        if any(marker in lowered for marker in _SERVICE_BUSY_HTML_MARKERS):
            raise FinixApiError("service busy html page")
        if "alipayobjects.com" in lowered and "<html" in lowered:
            raise FinixApiError("service busy html page")
        raise FinixApiError("full html page response")

    def _sha1(self, markdown: str | None) -> str:
        return hashlib.sha1((markdown or "").encode("utf-8")).hexdigest()
