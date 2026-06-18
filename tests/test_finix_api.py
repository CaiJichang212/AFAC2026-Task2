import json
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

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append({"url": url, "data": data, "files": files, "timeout": timeout})
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


def test_parse_chunk_posts_multipart_and_redacts_api_key(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    session = FakeSession([FakeResponse(200, "# parsed")])
    client = FinixApiClient(
        api_key="secret-key",
        user_ids=["finixA1001"],
        api_url="https://example.test/api",
        paths=paths,
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
    raw_path = paths.api_raw_dir / "doc" / "chunk-a.md"
    assert raw_path.read_text(encoding="utf-8") == "# parsed"
    log_text = (paths.logs_dir / "run.jsonl").read_text(encoding="utf-8")
    assert "secret-key" not in log_text
    assert "api_call" in log_text


def test_cache_hit_uses_raw_response_without_request(tmp_path):
    from finix_restore.finix_api import FinixApiClient

    paths = RunPaths.from_work_dir(tmp_path / "work")
    raw_dir = paths.api_raw_dir / "doc"
    raw_dir.mkdir(parents=True)
    (raw_dir / "chunk-a.md").write_text("cached markdown", encoding="utf-8")
    (raw_dir / "chunk-a.json").write_text(
        json.dumps({"chunk_id": "chunk-a", "image_sha1": "sha", "api_url": "https://example.test/api"}),
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
    assert sleeps == [1]

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
