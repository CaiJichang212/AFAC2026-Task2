from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.paths import RunPaths


def _config(tmp_path, input_dirs, limit=None, limit_per_dir=None):
    return RunConfig(
        input_dirs=input_dirs,
        output_csv=tmp_path / "submission.csv",
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
        dry_run=True,
        limit=limit,
        limit_per_dir=limit_per_dir,
    )


def test_limit_per_dir_samples_each_input_directory(tmp_path):
    from finix_restore.pipeline import Pipeline

    input_a = tmp_path / "a"
    input_b = tmp_path / "b"
    input_a.mkdir()
    input_b.mkdir()
    for name in ("a0.png", "a1.png", "a2.png"):
        Image.new("RGB", (10, 10), "white").save(input_a / name)
    for name in ("b0.png", "b1.png", "b2.png"):
        Image.new("RGB", (10, 10), "white").save(input_b / name)

    config = _config(tmp_path, [input_a, input_b], limit_per_dir=2)
    pipeline = Pipeline(config)

    sampled = pipeline._list_images(config.input_dirs)

    assert [path.name for path in sampled] == ["a0.png", "a1.png", "b0.png", "b1.png"]

    config = _config(tmp_path, [input_a, input_b], limit=3, limit_per_dir=2)
    pipeline = Pipeline(config)

    sampled = pipeline._list_images(config.input_dirs)

    assert [path.name for path in sampled] == ["a0.png", "a1.png", "b0.png"]
