import json

import pandas as pd
from PIL import Image

from finix_restore.config import RunConfig
from finix_restore.paths import RunPaths


def _config(tmp_path, input_dirs, output_csv):
    return RunConfig(
        input_dirs=input_dirs,
        output_csv=output_csv,
        paths=RunPaths.from_work_dir(tmp_path / "work"),
        api_key="secret",
        user_ids=["u1"],
        api_url="https://example.test/api",
        api={"timeout_seconds": 1, "max_retries": 0, "concurrency": 1, "per_user_concurrency": 1},
        chunk={
            "table": {
                "target_pixels": 8_000_000,
                "safe_max_pixels": 8_000_000,
                "full_page_max_pixels": 1_000_000,
                "horizontal_overlap": 160,
                "vertical_overlap": 220,
            }
        },
        merge={"dedup_similarity_threshold": 0.88},
        quality={"max_duplication_ratio": 1.0, "max_api_failure_ratio": 0.20, "max_reruns_per_file": 0},
        dry_run=False,
        force_api=False,
    )


def _table_html(col_band: int) -> str:
    rows = []
    for index in range(140):
        if col_band == 0:
            left = "终身" if index == 0 else f"项目{index}"
            right = "1" if index == 0 else str(index)
            rows.append(f"<tr><td>{left}</td><td>{right}</td></tr>")
        else:
            left = "男" if index == 0 else f"性别{index}"
            right = "2176" if index == 0 else str(2000 + index)
            rows.append(f"<tr><td>{left}</td><td>{right}</td></tr>")
    return f"<table>{''.join(rows)}</table>"


def test_pipeline_assembles_split_table_chunks_into_single_rows(tmp_path, monkeypatch):
    from finix_restore.models import ChunkText
    from finix_restore.pipeline import Pipeline

    class TableClient:
        def __init__(self, **kwargs):
            pass

        def parse_chunks(self, chunks, force_api=False):
            return [
                ChunkText(
                    chunk=chunk,
                    markdown=_table_html(chunk.col_band or 0),
                    block_type="table",
                    source="api",
                )
                for chunk in chunks
            ], 0

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    Image.new("RGB", (4800, 3200), "white").save(input_dir / "table.png")
    config = _config(tmp_path, [input_dir], tmp_path / "submission.csv")
    monkeypatch.setattr("finix_restore.pipeline.FinixApiClient", TableClient)

    report = Pipeline(config).run()
    df = pd.read_csv(config.output_csv)
    qc = json.loads((config.paths.qc_dir / "table.json").read_text(encoding="utf-8"))

    assert report.passed
    assert "<td>终身</td><td>1</td><td>男</td><td>2176</td>" in df.loc[0, "ground_truth"]
    metrics = qc["metrics"]
    assert "table_assembled_tables" in metrics
    assert "table_assembly_warning_count" in metrics
    assert "table_count" in metrics
    assert "table_count_before_assembly" in metrics
    assert "horizontal_split_chunks" in metrics
    assert "table_reference_chunks" in metrics
    assert "table_policy" in metrics
    assert "table_repaired_tags" in metrics
