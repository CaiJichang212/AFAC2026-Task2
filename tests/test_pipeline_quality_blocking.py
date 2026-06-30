import json
from pathlib import Path

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


def test_pipeline_resume_reruns_when_cached_quality_fails(tmp_path, monkeypatch):
    """缓存命中但质量门不过时, 必须忽略缓存并重跑, 而不是返回坏结果。"""
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    class HealsOnRerunClient:
        calls = 0

        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            HealsOnRerunClient.calls += 1
            return [
                ChunkText(chunk=chunk, markdown="# healed\n" + "x" * 2500, block_type="body", source="api")
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (5000, 300), "white").save(input_dir / "stale.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    config.quality["max_reruns_per_file"] = 1
    config.paths.merged_dir.mkdir(parents=True, exist_ok=True)
    # 缓存是一段未闭合的表格 HTML -> html_broken
    (config.paths.merged_dir / "stale.md").write_text(
        "<table><tr><td>broken", encoding="utf-8"
    )
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", HealsOnRerunClient)

    report = Pipeline(config).run()

    assert report.passed
    assert HealsOnRerunClient.calls == 1
    summary = json.loads((config.paths.qc_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is True
    # 缓存被新结果覆盖
    assert (config.paths.merged_dir / "stale.md").read_text(encoding="utf-8") != "<table><tr><td>broken"


def test_pipeline_retry_can_rechunk_with_rowband_policy(tmp_path, monkeypatch):
    from finix_restore.models import Chunk, ImageProfile, QualityReport
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    image_path = input_dir / "table.png"
    Image.new("RGB", (800, 600), "white").save(image_path)
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    config.quality["max_reruns_per_file"] = 1

    pipeline = Pipeline(config)
    chunk_calls: list[tuple[str, bool]] = []
    process_calls = {"count": 0}

    monkeypatch.setattr(
        pipeline.profiler,
        "profile_and_write",
        lambda image_path, out_dir: ImageProfile(
            file_name=image_path.name,
            path=image_path,
            width=800,
            height=600,
            pixels=480000,
            aspect=800 / 600,
            doc_type="table_page",
            risk_level="low",
        ),
    )
    monkeypatch.setattr(pipeline.layout_sentry, "analyze", lambda _: None)

    def fake_chunk(profile, hints, chunk_config=None):
        assert chunk_config is not None
        chunk_calls.append((chunk_config.table.policy_version, chunk_config.table.allow_horizontal_split))
        return [
            Chunk(
                chunk_id=f"chunk-{len(chunk_calls)}",
                file_name=profile.file_name,
                image_path=Path("/tmp/table.jpg"),
                bbox=(0, 0, 100, 100),
                row=0,
                col=0,
                overlap={"left": 0, "right": 0, "top": 0, "bottom": 0},
                image_sha1="sha1",
            )
        ]

    def fake_process_image_once(chunks, profile, force_api=False, concurrency_override=None, table_policy=None):
        process_calls["count"] += 1
        if process_calls["count"] == 1:
            return (
                ("A" * 5001) + "<table><tr><td>A</td></tr></table>",
                0,
                {
                    "table_assembled_tables": 1,
                    "table_assembly_warning_count": 0,
                    "table_count": 12,
                    "table_count_before_assembly": 12,
                    "horizontal_split_chunks": 2,
                    "table_reference_chunks": 0,
                    "table_policy": "table_grid_v2",
                    "table_repaired_tags": 0,
                },
            )
        return (
            ("B" * 5001) + "<table><tr><td>A</td></tr></table>",
            0,
            {
                "table_assembled_tables": 1,
                "table_assembly_warning_count": 0,
                "table_count": 1,
                "table_count_before_assembly": 2,
                "horizontal_split_chunks": 0,
                "table_reference_chunks": 1,
                "table_policy": "table_rowband_v2",
                "table_repaired_tags": 0,
            },
        )

    monkeypatch.setattr(pipeline, "_chunk", fake_chunk)
    monkeypatch.setattr(pipeline, "_process_image_once", fake_process_image_once)

    processed = pipeline._process_image(image_path)

    assert processed.quality.passed is True
    assert chunk_calls == [("grid_v2", True), ("rowband_v2", False)]
