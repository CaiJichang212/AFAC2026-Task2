import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from finix_restore.models import Chunk
from finix_restore.paths import RunPaths


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = []

    def post(self, url, data=None, files=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "data": data, "files": files, "headers": headers, "timeout": timeout}
        )
        return self.responses.pop(0)


def _chunk(tmp_path: Path, name: str = "doc.png", chunk_id: str = "chunk-a", sha1: str = "sha") -> Chunk:
    image_path = tmp_path / f"{chunk_id}.jpg"
    image_path.write_bytes(b"image-bytes")
    return Chunk(
        chunk_id=chunk_id,
        file_name=name,
        image_path=image_path,
        bbox=(0, 0, 10, 10),
        row=0,
        col=0,
        overlap={},
        image_sha1=sha1,
    )


def _response_sha1(markdown: str) -> str:
    return hashlib.sha1(markdown.encode("utf-8")).hexdigest()


def test_parse_chunk_posts_multipart_and_redacts_api_key(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    session = FakeSession([FakeResponse(200, "# parsed")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        run_id="run-123",
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "# parsed"
    assert result.source == "api"
    call = session.calls[0]
    assert call["url"] == "https://example.test/api"
    assert call["data"]["userId"] == "finixA1001"
    assert call["data"]["apiKey"] == "secret-key"
    assert call["data"]["fileName"] == "chunk-a.jpg"
    assert "file" in call["files"]
    assert call["headers"] == {"Expect": ""}
    raw_path = paths.api_raw_dir / "doc" / "chunk-a.md"
    assert raw_path.read_text(encoding="utf-8") == "# parsed"
    meta = json.loads((paths.api_raw_dir / "doc" / "chunk-a.json").read_text(encoding="utf-8"))
    assert meta["content_validated"] is True
    assert meta["validator_version"] == 1
    assert meta["response_sha1"] == _response_sha1("# parsed")
    log_text = (paths.logs_dir / "run.jsonl").read_text(encoding="utf-8")
    assert "secret-key" not in log_text
    assert "finixA1001" not in log_text
    assert "api_call" in log_text
    log_row = json.loads(log_text.strip())
    assert log_row["run_id"] == "run-123"
    assert log_row["user_id"] == "***"
    assert log_row["response_sha1"] == _response_sha1("# parsed")
    assert log_row["response_chars"] == len("# parsed")
    assert log_row["content_validated"] is True


def test_cache_hit_uses_raw_response_without_request(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    raw_dir = paths.api_raw_dir / "doc"
    raw_dir.mkdir(parents=True)
    markdown = "cached markdown"
    (raw_dir / "chunk-a.md").write_text(markdown, encoding="utf-8")
    (raw_dir / "chunk-a.json").write_text(
        json.dumps(
            {
                "chunk_id": "chunk-a",
                "image_sha1": "sha",
                "api_url": "https://example.test/api",
                "content_validated": True,
                "validator_version": 1,
                "response_sha1": _response_sha1(markdown),
            }
        ),
        encoding="utf-8",
    )
    session = FakeSession([FakeResponse(200, "should not be used")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "cached markdown"
    assert result.source == "cache"
    assert session.calls == []


def test_cache_without_validation_meta_is_ignored(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    raw_dir = paths.api_raw_dir / "doc"
    raw_dir.mkdir(parents=True)
    (raw_dir / "chunk-a.md").write_text("stale markdown", encoding="utf-8")
    (raw_dir / "chunk-a.json").write_text(
        json.dumps({"chunk_id": "chunk-a", "image_sha1": "sha", "api_url": "https://example.test/api"}),
        encoding="utf-8",
    )
    session = FakeSession([FakeResponse(200, "fresh markdown")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "fresh markdown"
    assert result.source == "api"
    assert len(session.calls) == 1
    meta = json.loads((raw_dir / "chunk-a.json").read_text(encoding="utf-8"))
    assert meta["content_validated"] is True
    assert meta["validator_version"] == 1
    assert meta["response_sha1"] == _response_sha1("fresh markdown")


def test_http_200_service_busy_html_is_retryable_and_not_cached(tmp_path):
    from finix_restore.finix_api import FinixApiClient, FinixApiError

    paths = RunPaths.from_work_dir(tmp_path / "work")
    html = (
        "<!DOCTYPE html><html><head><title>busy</title></head><body>"
        "服务器繁忙 顾客太多 <a id='J_retry_link'></a><div class='showTextWait'></div>"
        "支付宝版权所有"
        "</body></html>"
    )
    session = FakeSession([FakeResponse(200, html)])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        max_retries=0,
        session=session,
        sleep=lambda _: None,
    )

    with pytest.raises(FinixApiError, match="failed after retries"):
        client.parse_chunk(_chunk(tmp_path))

    assert not (paths.api_raw_dir / "doc" / "chunk-a.md").exists()
    log_text = (paths.logs_dir / "run.jsonl").read_text(encoding="utf-8")
    assert "secret-key" not in log_text


def test_http_200_service_busy_html_fragment_is_retryable_and_not_cached(tmp_path):
    from finix_restore.finix_api import FinixApiClient, FinixApiError

    paths = RunPaths.from_work_dir(tmp_path / "work")
    html_fragment = (
        "<div class='wait-tit'>顾客太多，客官请稍候</div>"
        "<a id='J_retry_link'>重试</a><script>showTextWait()</script>"
    )
    session = FakeSession([FakeResponse(200, html_fragment)])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        max_retries=0,
        session=session,
        sleep=lambda _: None,
    )

    with pytest.raises(FinixApiError, match="failed after retries"):
        client.parse_chunk(_chunk(tmp_path))

    assert not (paths.api_raw_dir / "doc" / "chunk-a.md").exists()


def test_html_table_fragment_is_valid_markdown_response(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    table_fragment = "<table><tr><td>保障责任</td></tr></table>"
    session = FakeSession([FakeResponse(200, table_fragment)])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == table_fragment
    assert (paths.api_raw_dir / "doc" / "chunk-a.md").read_text(encoding="utf-8") == table_fragment


def test_parse_chunks_returns_results_in_input_order_with_failures(tmp_path, monkeypatch):
    from finix_restore.finix_api import FinixApiClient, FinixApiError

    captured = {}

    class FakeFuture:
        def __init__(self, fn, *args, **kwargs):
            self._fn = fn
            self._args = args
            self._kwargs = kwargs

        def result(self, timeout=None):
            return self._fn(*self._args, **self._kwargs)

    class FakeExecutor:
        def __init__(self, max_workers):
            captured["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            return FakeFuture(fn, *args, **kwargs)

    monkeypatch.setattr("finix_restore.finix_api.ThreadPoolExecutor", FakeExecutor)

    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=RunPaths.from_work_dir(tmp_path / "work"),
        concurrency=3,
        session=FakeSession([]),
        sleep=lambda _: None,
    )

    chunks = [
        _chunk(tmp_path, name="a.png", chunk_id="a"),
        _chunk(tmp_path, name="b.png", chunk_id="b"),
        _chunk(tmp_path, name="c.png", chunk_id="c"),
    ]

    def fake_parse_chunk(chunk, force_api=False):
        if chunk.chunk_id == "b":
            raise FinixApiError("retryable network error: timeout")
        return type("ChunkTextLike", (), {})()

    def fake_parse_chunk(chunk, force_api=False):
        if chunk.chunk_id == "b":
            raise FinixApiError("retryable network error: timeout")
        from finix_restore.models import ChunkText

        return ChunkText(chunk=chunk, markdown=chunk.chunk_id.upper(), block_type="body", source="api")

    monkeypatch.setattr(client, "parse_chunk", fake_parse_chunk)

    results, failed_chunks = client.parse_chunks(chunks)

    assert captured["max_workers"] == 3
    assert [result.chunk.chunk_id for result in results] == ["a", "b", "c"]
    assert [result.markdown for result in results] == ["A", "", "C"]
    assert results[1].block_type == "unknown"
    assert failed_chunks == 1


def test_json_wrapped_response_extracts_markdown_content(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    wrapped = {
        "success": True,
        "result": {
            "result": json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "```markdown\n# 标题\n\n正文\n```",
                            }
                        }
                    ]
                }
            )
        },
    }
    session = FakeSession([FakeResponse(200, json.dumps(wrapped, ensure_ascii=False))])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
        session=session,
        sleep=lambda _: None,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "# 标题\n\n正文"
    assert (paths.api_raw_dir / "doc" / "chunk-a.md").read_text(encoding="utf-8") == "# 标题\n\n正文"


def test_user_ids_round_robin_and_concurrency_is_capped(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    session = FakeSession([FakeResponse(200, "one"), FakeResponse(200, "two"), FakeResponse(200, "three")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["u1", "u2"],
        api_url="https://example.test/api",
        paths=paths,
        concurrency=99,
        per_user_concurrency=1,
        session=session,
        sleep=lambda _: None,
    )

    client.parse_chunk(_chunk(tmp_path, name="a.png", chunk_id="a"))
    client.parse_chunk(_chunk(tmp_path, name="b.png", chunk_id="b"))
    client.parse_chunk(_chunk(tmp_path, name="c.png", chunk_id="c"))

    assert client.concurrency == 2
    assert [call["data"]["userId"] for call in session.calls] == ["u1", "u2", "u1"]


def test_retries_5xx_and_fails_fast_on_auth_error(tmp_path):
    from finix_restore.finix_api import FinixApiClient, FinixApiError

    paths = RunPaths.from_work_dir(tmp_path / "work")
    sleeps = []
    session = FakeSession([FakeResponse(500, "server error"), FakeResponse(200, "ok")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["u1"],
        api_url="https://example.test/api",
        paths=paths,
        max_retries=2,
        session=session,
        sleep=sleeps.append,
    )

    result = client.parse_chunk(_chunk(tmp_path))

    assert result.markdown == "ok"
    assert len(session.calls) == 2
    # 退避策略: retry_index=0 -> base=5s + 抖动(0~2.5s)
    assert len(sleeps) == 1
    assert 5.0 <= sleeps[0] < 7.5

    auth_session = FakeSession([FakeResponse(403, "forbidden"), FakeResponse(200, "unused")])
    auth_client = FinixApiClient(
        api_key="secret-key",
        user_ids=["u1"],
        api_url="https://example.test/api",
        paths=RunPaths.from_work_dir(tmp_path / "auth-work"),
        max_retries=2,
        session=auth_session,
        sleep=lambda _: None,
    )

    with pytest.raises(FinixApiError, match="authentication"):
        auth_client.parse_chunk(_chunk(tmp_path, chunk_id="auth"))
    assert len(auth_session.calls) == 1


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

        def post(self, url, data=None, files=None, headers=None, timeout=None):
            self.limiter.post_happened_inside_limiter = self.limiter.active
            return super().post(url, data=data, files=files, headers=headers, timeout=timeout)

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
