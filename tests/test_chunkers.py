import json

import yaml
from PIL import Image

from finix_restore.chunk_config import ChunkConfig
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

    manifest = json.loads((tmp_path / "chunks" / "table" / "manifest.json").read_text())
    assert manifest["chunk_policy"] == "table_grid_v2"
    assert manifest["content_box"] == [0, 0, 6000, 4200]
    last_chunk = manifest["chunks"][-1]
    assert last_chunk["is_last_row"] is True
    assert last_chunk["is_last_col"] is True
    assert last_chunk["cut_source"] in {"full_page", "grid"}
    assert isinstance(last_chunk["risk_flags"], list)


def test_default_table_config_splits_15m_pixel_pages_for_api_stability():
    config = yaml.safe_load(open("configs/default.yaml", encoding="utf-8"))
    chunk = config["chunk"]

    assert chunk["hard_max_pixels"] == 16_777_216
    assert chunk["table"]["full_page_max_pixels"] <= 8_000_000
    assert chunk["table"]["target_pixels"] == 6_000_000


def test_long_dynamic_height_respects_safe_max_pixels(tmp_path):
    image_path = tmp_path / "wide_long.jpg"
    Image.new("RGB", (5000, 12000), "white").save(image_path)
    profile = _profile(image_path, 5000, 12000, "long_strip")
    hints = LayoutHints((0, 0, 5000, 12000), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "long": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 8_000_000,
            "max_window_height": 4000,
            "min_window_height": 1200,
            "vertical_overlap": 320,
            "blank_band_search_px": 360,
        }
    })
    chunks = LongStripChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert all(c.chunk_pixels <= 8_000_000 for c in chunks)
    assert max(c.bbox[3] - c.bbox[1] for c in chunks) <= 1600


def test_long_chunks_use_content_box_with_crop_margin(tmp_path):
    image_path = tmp_path / "long_with_margin.jpg"
    Image.new("RGB", (1000, 1000), "white").save(image_path)
    profile = _profile(image_path, 1000, 1000, "long_strip")
    hints = LayoutHints((100, 200, 900, 800), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "crop_margin_px": 24,
        "long": {
            "target_pixels": 1_000_000,
            "max_window_height": 800,
            "min_window_height": 200,
            "vertical_overlap": 0,
        },
    })
    chunks = LongStripChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)
    manifest = json.loads((tmp_path / "chunks" / "long_with_margin" / "manifest.json").read_text())

    assert manifest["content_box"] == [76, 176, 924, 824]
    assert chunks[0].bbox[0] == 76
    assert chunks[0].bbox[2] == 924


def test_table_overlap_included_in_pixel_budget(tmp_path):
    image_path = tmp_path / "table_budget.jpg"
    Image.new("RGB", (6000, 4200), "white").save(image_path)
    profile = _profile(image_path, 6000, 4200, "table_page")
    hints = LayoutHints((0, 0, 6000, 4200), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 6_000_000,
            "full_page_max_pixels": 1_000_000,
            "horizontal_overlap": 160,
            "vertical_overlap": 220,
        }
    })

    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) > 1
    assert all(c.chunk_pixels <= 6_000_000 for c in chunks)


def test_last_row_col_overlap_metadata(tmp_path):
    image_path = tmp_path / "table_lastrc.jpg"
    Image.new("RGB", (6000, 4200), "white").save(image_path)
    profile = _profile(image_path, 6000, 4200, "table_page")
    hints = LayoutHints((0, 0, 6000, 4200), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 6_000_000,
            "full_page_max_pixels": 1_000_000,
            "horizontal_overlap": 160,
            "vertical_overlap": 220,
        }
    })

    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    for chunk in chunks:
        if chunk.is_last_col:
            assert chunk.overlap["right"] == 0
        if chunk.is_last_row:
            assert chunk.overlap["bottom"] == 0
        if not chunk.is_last_col:
            assert chunk.overlap["right"] > 0
        if not chunk.is_last_row:
            assert chunk.overlap["bottom"] > 0


def test_table_cut_adjusts_to_blank_band(tmp_path):
    image_path = tmp_path / "table_band.jpg"
    Image.new("RGB", (6000, 4200), "white").save(image_path)
    profile = _profile(image_path, 6000, 4200, "table_page")
    hints = LayoutHints(
        (0, 0, 6000, 4200),
        [(2080, 2160)],
        [(2980, 3060)],
        0.5,
        1,
    )
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 8_000_000,
            "full_page_max_pixels": 1_000_000,
            "horizontal_overlap": 160,
            "vertical_overlap": 220,
            "cut_search_px": 260,
        }
    })

    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert any(c.cut_source == "blank_band" for c in chunks)
    for c in chunks:
        assert c.bbox[0] >= 0 and c.bbox[2] <= 6000
        assert c.bbox[1] >= 0 and c.bbox[3] <= 4200


def test_long_cut_adjusts_to_horizontal_blank_band(tmp_path):
    image_path = tmp_path / "long_blank_band.jpg"
    Image.new("RGB", (1500, 8000), "white").save(image_path)
    profile = _profile(image_path, 1500, 8000, "long_strip")
    hints = LayoutHints((0, 0, 1500, 8000), [(3150, 3230)], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "long": {
            "target_pixels": 4_800_000,
            "safe_max_pixels": 9_000_000,
            "max_window_height": 4000,
            "min_window_height": 1500,
            "vertical_overlap": 320,
            "blank_band_search_px": 360,
        }
    })
    chunks = LongStripChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert chunks[0].bbox[3] == 3190
    assert chunks[0].cut_source == "blank_band"
