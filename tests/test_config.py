from pathlib import Path

import pytest

from finix_restore.cli import parse_args
from finix_restore.config import ConfigError, load_config
from finix_restore.paths import RunPaths


def _write_yaml(path: Path) -> None:
    path.write_text(
        """
api:
  url: "${FINIX_API_URL}"
  timeout_seconds: 240
  max_retries: 3
  concurrency: 8
  per_user_concurrency: 1
chunk:
  hard_max_pixels: 16777216
  safe_max_pixels: 12000000
  min_pixels: 4096
  crop_margin_px: 24
  long:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    max_window_height: 4000
    min_window_height: 1800
    vertical_overlap: 320
    blank_band_search_px: 360
  table:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    full_page_max_pixels: 8000000
    horizontal_overlap: 160
    vertical_overlap: 220
    cut_search_px: 260
  normal:
    full_page_max_pixels: 12000000
    target_pixels: 8000000
merge:
  dedup_window_chars_long: 1200
  dedup_window_chars_table: 600
  dedup_similarity_threshold: 0.88
quality:
  max_duplication_ratio: 0.18
  max_api_failure_ratio: 0.20
  max_reruns_per_file: 2
runtime:
  image_concurrency: 3
""",
        encoding="utf-8",
    )


def test_config_requires_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.delenv("FINIX_API_KEY", raising=False)
    monkeypatch.setenv("apiKey", "")
    monkeypatch.setenv("FINIX_USER_IDS", "u1")
    monkeypatch.setenv("userIds", "")

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

    with pytest.raises(ConfigError, match="FINIX_API_KEY"):
        load_config(args)


def test_config_requires_user_ids(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("apiKey", "")
    monkeypatch.setenv("FINIX_USER_IDS", " , ")
    monkeypatch.setenv("userIds", "")

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

    with pytest.raises(ConfigError, match="FINIX_USER_IDS"):
        load_config(args)


def test_dry_run_does_not_require_api_credentials(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.delenv("FINIX_API_KEY", raising=False)
    monkeypatch.delenv("FINIX_USER_IDS", raising=False)
    monkeypatch.setenv("apiKey", "")
    monkeypatch.setenv("userIds", "")

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
            "--dry_run",
        ]
    )

    config = load_config(args)

    assert config.dry_run is True
    assert config.api_key == ""
    assert config.user_ids == ["dry_run"]


def test_config_accepts_legacy_env_key_names(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.delenv("FINIX_API_KEY", raising=False)
    monkeypatch.delenv("FINIX_USER_IDS", raising=False)
    monkeypatch.setenv("apiKey", "legacy-secret")
    monkeypatch.setenv("userIds", "u1,u2")

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

    assert config.api_key == "legacy-secret"
    assert config.user_ids == ["u1", "u2"]
    assert config.snapshot()["api_key"] == "***"
    assert config.snapshot()["user_ids"] == ["***", "***"]
    assert "u1" not in str(config.snapshot())
    assert "u2" not in str(config.snapshot())


def test_config_keeps_repeated_input_dirs_and_caps_concurrency(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_a = tmp_path / "a"
    input_b = tmp_path / "b"
    input_a.mkdir()
    input_b.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1,u2")
    monkeypatch.setenv("FINIX_API_URL", "https://example.test/api")

    args = parse_args(
        [
            "--input_dir",
            str(input_a),
            "--input_dir",
            str(input_b),
            "--output_csv",
            str(tmp_path / "submission.csv"),
            "--work_dir",
            str(tmp_path / "work"),
            "--config",
            str(config_path),
            "--limit_per_dir",
            "3",
        ]
    )
    config = load_config(args)

    assert config.input_dirs == [input_a, input_b]
    assert config.limit_per_dir == 3
    assert config.api["concurrency"] == 2
    assert config.api_url == "https://example.test/api"
    assert config.snapshot()["api_key"] == "***"
    assert config.snapshot()["user_ids"] == ["***", "***"]
    assert config.paths.logs_dir.exists()


def test_run_paths_creates_expected_directories(tmp_path):
    paths = RunPaths.from_work_dir(tmp_path / "outputs" / "run")

    assert paths.profiles_dir.exists()
    assert paths.chunks_dir.exists()
    assert paths.api_raw_dir.exists()
    assert paths.normalized_dir.exists()
    assert paths.merged_dir.exists()
    assert paths.qc_dir.exists()
    assert paths.logs_dir.exists()
    assert paths.metrics_dir.exists()


def test_config_reads_limit_per_dir_argument(tmp_path, monkeypatch):
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
            "--limit_per_dir",
            "5",
        ]
    )

    config = load_config(args)

    assert config.limit_per_dir == 5


def test_config_reads_image_concurrency_from_runtime_yaml(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    _write_yaml(config_path)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1,u2,u3")

    args = parse_args(
        [
            "--input_dir", str(input_dir),
            "--output_csv", str(tmp_path / "submission.csv"),
            "--work_dir", str(tmp_path / "work"),
            "--config", str(config_path),
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
            "--input_dir", str(input_dir),
            "--output_csv", str(tmp_path / "submission.csv"),
            "--work_dir", str(tmp_path / "work"),
            "--config", str(config_path),
            "--image_concurrency", "2",
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
            "--input_dir", str(input_dir),
            "--output_csv", str(tmp_path / "submission.csv"),
            "--work_dir", str(tmp_path / "work"),
            "--config", str(config_path),
            "--image_concurrency", "0",
        ]
    )

    with pytest.raises(ConfigError, match="runtime.image_concurrency must be >= 1"):
        load_config(args)


def test_config_handles_empty_runtime_yaml_block(tmp_path, monkeypatch):
    config_path = tmp_path / "default.yaml"
    config_path.write_text(
        """
api:
  url: "${FINIX_API_URL}"
  timeout_seconds: 240
  max_retries: 3
  concurrency: 2
  per_user_concurrency: 1
chunk:
  hard_max_pixels: 16777216
  safe_max_pixels: 12000000
  min_pixels: 4096
  crop_margin_px: 24
  long:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    max_window_height: 4000
    min_window_height: 1800
    vertical_overlap: 320
    blank_band_search_px: 360
  table:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    full_page_max_pixels: 8000000
    horizontal_overlap: 160
    vertical_overlap: 220
    cut_search_px: 260
  normal:
    full_page_max_pixels: 12000000
    target_pixels: 8000000
merge:
  dedup_similarity_threshold: 0.88
quality:
  max_duplication_ratio: 0.18
  max_api_failure_ratio: 0.20
  max_reruns_per_file: 2
runtime:
""",
        encoding="utf-8",
    )
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    monkeypatch.setenv("FINIX_API_KEY", "secret")
    monkeypatch.setenv("FINIX_USER_IDS", "u1")

    args = parse_args(
        [
            "--input_dir", str(input_dir),
            "--output_csv", str(tmp_path / "submission.csv"),
            "--work_dir", str(tmp_path / "work"),
            "--config", str(config_path),
        ]
    )

    config = load_config(args)

    assert config.runtime["image_concurrency"] == 1
