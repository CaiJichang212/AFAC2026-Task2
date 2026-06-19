import threading

import pandas as pd
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.models import ProcessedFile, QualityReport
from finix_restore.paths import RunPaths


WAIT_TIMEOUT = 2


def _config(tmp_path, input_dirs, image_concurrency=2):
    return RunConfig(
        input_dirs=input_dirs,
        output_csv=tmp_path / "submission.csv",
        paths=RunPaths.from_work_dir(tmp_path / "work"),
        api_key="secret",
        user_ids=["u1", "u2"],
        api_url="https://example.test/api",
        api={"timeout_seconds": 1, "max_retries": 0, "concurrency": 2, "per_user_concurrency": 1},
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
        runtime={"image_concurrency": image_concurrency},
    )


def test_pipeline_processes_images_concurrently_but_writes_csv_in_input_order(tmp_path, monkeypatch):
    from finix_restore.pipeline import Pipeline

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (120, 240), "white").save(input_dir / "a.png")
    Image.new("RGB", (120, 240), "white").save(input_dir / "b.png")

    a_started = threading.Event()
    b_started = threading.Event()
    release_a = threading.Event()

    def fake_process_image(self, image_path):
        if image_path.name == "a.png":
            a_started.set()
            assert b_started.wait(WAIT_TIMEOUT)
            assert release_a.wait(WAIT_TIMEOUT)
            return ProcessedFile(
                file_name="a.png",
                markdown="A",
                quality=QualityReport(True, [], {"doc_type": "normal_page"}),
            )
        assert a_started.wait(WAIT_TIMEOUT)
        b_started.set()
        release_a.set()
        return ProcessedFile(
            file_name="b.png",
            markdown="B",
            quality=QualityReport(True, [], {"doc_type": "normal_page"}),
        )

    monkeypatch.setattr(Pipeline, "_process_image", fake_process_image)
    config = _config(tmp_path, [input_dir], image_concurrency=2)

    report = Pipeline(config).run()

    df = pd.read_csv(config.output_csv)
    assert report.passed
    assert list(df["file_name"]) == ["a.png", "b.png"]
    assert list(df["ground_truth"]) == ["A", "B"]
