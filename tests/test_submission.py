import pandas as pd
import pytest
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.paths import RunPaths


def _config(tmp_path, input_dirs, output_csv, dry_run=True):
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
        quality={"max_duplication_ratio": 0.18, "max_api_failure_ratio": 0.20, "max_reruns_per_file": 2},
        dry_run=dry_run,
    )


def test_submission_writer_writes_readable_schema(tmp_path):
    from finix_restore.submission import SubmissionWriter

    output_csv = tmp_path / "submission.csv"

    report = SubmissionWriter().write(
        [{"file_name": "a.png", "ground_truth": "# A\n"}],
        output_csv,
        expected_file_names=["a.png"],
    )

    df = pd.read_csv(output_csv)
    assert report.passed
    assert list(df.columns) == ["file_name", "ground_truth"]
    assert len(df) == 1


def test_pipeline_dry_run_generates_profiles_manifests_and_merged_csv(tmp_path):
    from finix_restore.pipeline import Pipeline

    input_a = tmp_path / "a"
    input_b = tmp_path / "b"
    input_a.mkdir()
    input_b.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_a / "one.png")
    Image.new("RGB", (140, 260), "white").save(input_b / "two.png")
    config = _config(tmp_path, [input_a, input_b], tmp_path / "submission.csv", dry_run=True)

    report = Pipeline(config).run()

    df = pd.read_csv(config.output_csv)
    assert report.passed
    assert list(df["file_name"]) == ["one.png", "two.png"]
    assert (config.paths.profiles_dir / "one.json").exists()
    assert (config.paths.chunks_dir / "one" / "manifest.json").exists()
    assert (config.paths.merged_dir / "one.md").exists()
    assert (config.paths.qc_dir / "one.json").exists()


def test_pipeline_blocks_duplicate_input_file_names(tmp_path):
    from finix_restore.pipeline import Pipeline, PipelineError

    input_a = tmp_path / "a"
    input_b = tmp_path / "b"
    input_a.mkdir()
    input_b.mkdir()
    Image.new("RGB", (20, 20), "white").save(input_a / "same.png")
    Image.new("RGB", (20, 20), "white").save(input_b / "same.png")
    config = _config(tmp_path, [input_a, input_b], tmp_path / "submission.csv", dry_run=True)

    with pytest.raises(PipelineError, match="duplicate_input_file_name"):
        Pipeline(config).run()


def test_pipeline_resume_reuses_existing_merged_markdown_without_api(tmp_path):
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "cached.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv", dry_run=False)
    config.paths.merged_dir.mkdir(parents=True, exist_ok=True)
    (config.paths.merged_dir / "cached.md").write_text("# cached result\n", encoding="utf-8")

    report = Pipeline(config).run()

    df = pd.read_csv(config.output_csv)
    assert report.passed
    assert df.loc[0, "ground_truth"] == "# cached result\n"


def test_pipeline_records_retry_exhausted_chunk_failure_and_still_writes_csv(tmp_path, monkeypatch):
    from finix_restore.finix_api import FinixApiError
    from finix_restore.pipeline import Pipeline

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunk(self, chunk, force_api=False):
            raise FinixApiError("FinixDoc-VL request failed after retries: timeout")

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "failed.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv", dry_run=False)
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", FailingClient)

    report = Pipeline(config).run()

    df = pd.read_csv(config.output_csv)
    qc = (config.paths.qc_dir / "failed.json").read_text(encoding="utf-8")
    assert report.passed
    assert df.loc[0, "file_name"] == "failed.png"
    assert "api_failure_ratio_high" in qc
    assert "empty_output" in qc


def test_pipeline_writes_normalized_chunk_outputs(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    class SuccessfulClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunk(self, chunk, force_api=False):
            return ChunkText(chunk=chunk, markdown="##1.1 标题  ", block_type="body", source="api")

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "normalized.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv", dry_run=False)
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", SuccessfulClient)

    Pipeline(config).run()

    normalized_files = list((config.paths.normalized_dir / "normalized").glob("*.md"))
    assert len(normalized_files) == 1
    assert normalized_files[0].read_text(encoding="utf-8") == "## 1.1 标题\n"
