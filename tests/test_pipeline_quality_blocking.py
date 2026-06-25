import json

import pandas as pd
import pytest
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.models import Chunk, ImageProfile
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


def test_pipeline_removes_stale_submission_when_quality_fails(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline, PipelineError

    class EmptyClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(chunk=chunk, markdown="", block_type="unknown", source="api")
                for chunk in chunks
            ], len(chunks)

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "failed.png")
    output_csv = tmp_path / "submission.csv"
    output_csv.write_text("file_name,ground_truth\nold.png,stale\n", encoding="utf-8")
    config = _config(tmp_path, [input_dir], output_csv)
    config.quality["max_reruns_per_file"] = 0
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", EmptyClient)

    with pytest.raises(PipelineError, match="quality gate failed"):
        Pipeline(config).run()

    assert not output_csv.exists()


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


def test_pipeline_rerun_applies_retry_planner_concurrency(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    class RetryConcurrencyClient:
        init_concurrency = []
        calls = 0

        def __init__(self, **kwargs):
            self.init_concurrency.append(kwargs["concurrency"])

        def parse_chunks(self, chunks, force_api=False):
            RetryConcurrencyClient.calls += 1
            if RetryConcurrencyClient.calls == 1:
                return [
                    ChunkText(chunk=chunk, markdown="", block_type="unknown", source="api")
                    for chunk in chunks
                ], len(chunks)
            return [
                ChunkText(chunk=chunk, markdown="# ok", block_type="body", source="api")
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "serial-rerun.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    config.api["concurrency"] = 4
    config.quality["max_reruns_per_file"] = 1
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", RetryConcurrencyClient)

    report = Pipeline(config).run()

    assert report.passed
    assert RetryConcurrencyClient.init_concurrency == [4, 1]


def test_pipeline_blocks_non_empty_broken_table_html(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText, TableRepairResult
    from finix_restore.pipeline import Pipeline, PipelineError
    from finix_restore.table_assembler import TableAssemblyResult

    class BrokenTableClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(
                    chunk=chunk,
                    markdown="<table><tr><td>保障责任",
                    block_type="table",
                    source="api",
                )
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (4800, 3200), "white").save(input_dir / "broken-table.png")
    output_csv = tmp_path / "submission.csv"
    config = _config(tmp_path, [input_dir], output_csv)
    config.quality["max_reruns_per_file"] = 0
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", BrokenTableClient)
    monkeypatch.setattr(
        "finix_restore.pipeline.TableRowAssembler.assemble",
        lambda self, ordered_chunks: TableAssemblyResult(
            markdown="<table><tr><td>保障责任",
            warnings=(),
            assembled_tables=0,
        ),
    )
    monkeypatch.setattr(
        "finix_restore.pipeline.TableMerger.repair",
        lambda self, markdown: TableRepairResult(markdown=markdown, repaired_tags=0, warnings=[]),
    )

    with pytest.raises(PipelineError, match="quality gate failed"):
        Pipeline(config).run()

    assert not output_csv.exists()
    summary = json.loads((config.paths.qc_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is False
    assert summary["risk_counts"]["html_broken"] == 1


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


def test_dry_run_qc_records_long_cutline_metrics(tmp_path):
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    image_path = input_dir / "long.png"
    Image.new("RGB", (300, 6000), "white").save(image_path)
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv", dry_run=True)
    pipeline = Pipeline(config)
    profile = ImageProfile(
        file_name="long.png",
        path=image_path,
        width=300,
        height=6000,
        pixels=1_800_000,
        aspect=20.0,
        doc_type="long_strip",
        risk_level="low",
    )
    chunks = [
        Chunk(
            chunk_id="c1",
            file_name="long.png",
            image_path=image_path,
            bbox=(0, 0, 300, 2200),
            row=0,
            col=0,
            overlap={"top": 0, "bottom": 320, "left": 0, "right": 0},
            image_sha1="sha1",
            chunk_pixels=660_000,
            cut_source="blank_band",
        ),
        Chunk(
            chunk_id="c2",
            file_name="long.png",
            image_path=image_path,
            bbox=(0, 1880, 300, 4200),
            row=1,
            col=0,
            overlap={"top": 320, "bottom": 320, "left": 0, "right": 0},
            image_sha1="sha1",
            chunk_pixels=696_000,
            cut_source="fixed_cut",
        ),
        Chunk(
            chunk_id="c3",
            file_name="long.png",
            image_path=image_path,
            bbox=(0, 3880, 300, 6000),
            row=2,
            col=0,
            overlap={"top": 320, "bottom": 0, "left": 0, "right": 0},
            image_sha1="sha1",
            chunk_pixels=636_000,
            is_last_row=True,
            is_last_col=True,
            cut_source="fixed_cut",
        ),
    ]

    pipeline._write_dry_run_qc(profile, chunks)

    qc = json.loads((config.paths.qc_dir / "long.json").read_text(encoding="utf-8"))
    assert qc["metrics"]["blank_cut_count"] == 1
    assert qc["metrics"]["fixed_cut_count"] == 1
    assert qc["metrics"]["blank_cut_ratio"] == 0.5
