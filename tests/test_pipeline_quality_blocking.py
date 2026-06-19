import json

import pandas as pd
import pytest
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.paths import RunPaths


def _config(tmp_path, input_dirs, output_csv, dry_run=False, force_api=False):
    return RunConfig(
        input_dirs=input_dirs,
        output_csv=output_csv,
        paths=RunPaths.from_work_dir(tmp_path / "work"),
        api_key="secret",
        user_ids=["u1"],
        api_url="https://example.test/api",
        api={"timeout_seconds": 1, "max_retries": 0, "concurrency": 1, "per_user_concurrency": 1},
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
        dry_run=dry_run,
        force_api=force_api,
    )


def test_pipeline_blocks_submission_when_file_qc_fails(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline, PipelineError

    class BusyThenDoneClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(
                    chunk=chunk,
                    markdown=(
                        "<!DOCTYPE html><html><head></head><body>"
                        "服务器繁忙 顾客太多 <div id='J_retry_link'></div><div class='showTextWait'></div>"
                        "支付宝版权所有"
                        "</body></html>"
                    ),
                    block_type="body",
                    source="api",
                )
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "failed.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", BusyThenDoneClient)

    with pytest.raises(PipelineError, match="quality gate failed"):
        Pipeline(config).run()

    assert not config.output_csv.exists()
    summary = json.loads((config.paths.qc_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is False
    assert summary["failed_files"] == ["failed.png"]
    assert summary["risk_counts"]["service_busy_html"] == 1
    assert summary["risk_counts"]["full_html_page"] == 1


def test_pipeline_reruns_once_after_retryable_quality_failure(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    class RetryableClient:
        calls = 0

        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            RetryableClient.calls += 1
            if RetryableClient.calls == 1:
                return [
                    ChunkText(
                        chunk=chunk,
                        markdown=(
                            "<!DOCTYPE html><html><head></head><body>"
                            "服务器繁忙 <div id='J_retry_link'></div><div class='showTextWait'></div>"
                            "</body></html>"
                        ),
                        block_type="body",
                        source="api",
                    )
                    for chunk in chunks
                ], 0
            return [
                ChunkText(chunk=chunk, markdown="# ok", block_type="body", source="api")
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "rerun.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    config.quality["max_reruns_per_file"] = 1
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", RetryableClient)

    report = Pipeline(config).run()

    assert report.passed
    df = pd.read_csv(config.output_csv)
    assert df.loc[0, "ground_truth"] == "# ok\n"
    summary = json.loads((config.paths.qc_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is True
    assert summary["files"][0]["rerun_count"] == 1


def test_pipeline_resume_hits_merged_cache_still_records_qc_metric(tmp_path):
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (5000, 300), "white").save(input_dir / "cached.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    config.paths.merged_dir.mkdir(parents=True, exist_ok=True)
    (config.paths.merged_dir / "cached.md").write_text("X" * 2500, encoding="utf-8")

    report = Pipeline(config).run()

    assert report.passed
    qc = json.loads((config.paths.qc_dir / "cached.json").read_text(encoding="utf-8"))
    assert qc["metrics"]["from_merged_cache"] == 1
