import json

import yaml
from PIL import Image

from finix_restore.chunkers import LongStripChunker, TableGridChunker
from finix_restore.layout_sentry import LayoutHints
from finix_restore.models import ImageProfile


def _profile(path, width, height, doc_type):
    return ImageProfile(
        file_name=path.name,
        path=path,
        width=width,
        height=height,
        pixels=width * height,
        aspect=max(width, height) / min(width, height),
        doc_type=doc_type,
        risk_level="low",
    )


def _assert_cover_height(chunks, width, height):
    covered = [False] * height
    for chunk in chunks:
        x0, y0, x1, y1 = chunk.bbox
        assert 0 <= x0 < x1 <= width
        assert 0 <= y0 < y1 <= height
        for y in range(y0, y1):
            covered[y] = True
    assert all(covered)


def test_long_strip_chunks_cover_height_and_have_stable_ids(tmp_path):
    image_path = tmp_path / "long.jpg"
    Image.new("RGB", (1500, 10000), "white").save(image_path)
    profile = _profile(image_path, 1500, 10000, "long_strip")
    hints = LayoutHints((0, 0, 1500, 10000), [], [], 0.0, 1)
    chunker = LongStripChunker(tmp_path / "chunks", window_height=4000, overlap=320)

    chunks = chunker.chunk(profile, hints)
    chunks_again = chunker.chunk(profile, hints)
    manifest = json.loads((tmp_path / "chunks" / "long" / "manifest.json").read_text())

    _assert_cover_height(chunks, 1500, 10000)
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in chunks_again]
    assert len(manifest["chunks"]) == len(chunks)
    assert manifest["content_box"] == [0, 0, 1500, 10000]
    assert manifest["chunk_policy"] == "long_dynamic_v1"
    first_chunk_payload = manifest["chunks"][0]
    assert {"chunk_pixels", "is_last_row", "is_last_col", "cut_source", "risk_flags"} <= set(first_chunk_payload)
    assert isinstance(first_chunk_payload["bbox"], list)
    assert isinstance(first_chunk_payload["risk_flags"], list)


def test_table_grid_chunks_respect_bounds_and_max_pixels(tmp_path):
    image_path = tmp_path / "table.jpg"
    Image.new("RGB", (6000, 4200), "white").save(image_path)
    profile = _profile(image_path, 6000, 4200, "table_page")
    hints = LayoutHints((0, 0, 6000, 4200), [], [], 0.5, 1)
    chunker = TableGridChunker(
        tmp_path / "chunks",
        max_chunk_pixels=12_000_000,
        full_page_max_pixels=16_000_000,
        horizontal_overlap=160,
        vertical_overlap=220,
    )

    chunks = chunker.chunk(profile, hints)

    assert len(chunks) > 1
    for chunk in chunks:
        x0, y0, x1, y1 = chunk.bbox
        assert 0 <= x0 < x1 <= 6000
        assert 0 <= y0 < y1 <= 4200
        assert (x1 - x0) * (y1 - y0) <= 13_800_000


def test_default_table_config_splits_15m_pixel_pages_for_api_stability():
    config = yaml.safe_load(open("configs/default.yaml", encoding="utf-8"))
    chunk = config["chunk"]

    assert chunk["hard_max_pixels"] == 16_777_216
    assert chunk["table"]["full_page_max_pixels"] <= 8_000_000
    assert chunk["table"]["target_pixels"] == 6_000_000
