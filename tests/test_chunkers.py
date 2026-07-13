import json
from pathlib import Path

import yaml
from PIL import Image

from finix_restore.chunk_config import ChunkConfig
from finix_restore.chunkers import LongStripChunker, PageChunker, TableGridChunker
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
    assert chunks[0].row_band == 0
    assert chunks[0].col_band == 0
    assert chunks[0].base_bbox is not None
    assert chunks[0].overlap_bbox == chunks[0].bbox
    assert chunks[0].requires_row_assembly is True
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
    assert last_chunk["cut_source"] in {"full_page", "fixed_cut", "blank_band"}
    assert isinstance(last_chunk["risk_flags"], list)
    assert manifest["chunks"][0]["row_band"] == 0
    assert manifest["chunks"][0]["col_band"] == 0
    assert manifest["chunks"][0]["base_bbox"] is not None
    assert manifest["chunks"][0]["overlap_bbox"] == manifest["chunks"][0]["bbox"]
    assert "requires_row_assembly" in manifest["chunks"][0]
    assert manifest["chunks"][0]["sent_width"] == 3160
    assert manifest["chunks"][0]["sent_height"] == 2320
    assert manifest["chunks"][0]["render_scale"] == 1.0
    assert manifest["chunks"][0]["variant_kind"] == "table_crop"
    assert manifest["chunks"][0]["anchor_bbox"] is None


def test_default_table_config_splits_15m_pixel_pages_for_api_stability():
    config = yaml.safe_load(open("configs/default.yaml", encoding="utf-8"))
    chunk = config["chunk"]

    assert chunk["hard_max_pixels"] == 16_777_216
    assert chunk["table"]["full_page_max_pixels"] <= 8_000_000
    assert chunk["table"]["target_pixels"] == 5_000_000
    assert chunk["table"]["safe_max_pixels"] == 7_000_000


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


def test_long_cutline_planner_prefers_blank_band_and_falls_back_to_fixed_cut():
    from finix_restore.cutline_planner import LongCutlinePlanner

    planner = LongCutlinePlanner()

    cut = planner.choose_cut(target_y=3200, y0=0, cy1=8000, bands=[(3150, 3230)], search_px=360)
    assert cut.y1 == 3190
    assert cut.source == "blank_band"

    fallback = planner.choose_cut(target_y=3200, y0=3199, cy1=8000, bands=[], search_px=360)
    assert fallback.y1 == 3200
    assert fallback.source == "fixed_cut"


def test_normal_page_chunker_prefers_full_page(tmp_path):
    image_path = tmp_path / "normal.jpg"
    Image.new("RGB", (3000, 3000), "white").save(image_path)
    profile = _profile(image_path, 3000, 3000, "normal_page")
    hints = LayoutHints((0, 0, 3000, 3000), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "normal": {"full_page_max_pixels": 12_000_000, "target_pixels": 8_000_000},
    })
    chunks = PageChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) == 1
    assert chunks[0].cut_source == "full_page"
    assert chunks[0].bbox == (0, 0, 3000, 3000)

    manifest = json.loads((tmp_path / "chunks" / "normal" / "manifest.json").read_text())
    assert manifest["chunk_policy"] == "normal_page_v1"


def test_normal_page_chunker_grids_when_exceeds_full_page(tmp_path):
    image_path = tmp_path / "normal_big.jpg"
    Image.new("RGB", (5000, 4000), "white").save(image_path)  # 20M > 12M
    profile = _profile(image_path, 5000, 4000, "normal_page")
    hints = LayoutHints((0, 0, 5000, 4000), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "normal": {"full_page_max_pixels": 12_000_000, "target_pixels": 8_000_000},
        "table": {"horizontal_overlap": 100, "vertical_overlap": 100},
    })
    chunks = PageChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) > 1
    for c in chunks:
        # 不超过 cfg.hard_max_pixels (16777216)
        assert c.chunk_pixels <= 16_777_216

    manifest = json.loads((tmp_path / "chunks" / "normal_big" / "manifest.json").read_text())
    assert manifest["chunk_policy"] == "normal_page_v1"


def test_table_blank_band_adjustment_does_not_exceed_safe_max(tmp_path):
    """Regression: blank-band shift used to enlarge a neighbouring cell past
    safe_max once overlap was added. The chunker now rolls back offending
    band cuts to keep every chunk_pixels <= safe_max."""
    image_path = tmp_path / "table_band_safe.jpg"
    Image.new("RGB", (6000, 4200), "white").save(image_path)
    profile = _profile(image_path, 6000, 4200, "table_page")
    # Reproduces a real review finding: with target/safe = 6M and a vertical
    # band whose center sits at x=3020 (base x cut is 3000, so drift = +20px),
    # the previous implementation produced a 3140x2320 = 7,284,800 pixel cell.
    hints = LayoutHints(
        (0, 0, 6000, 4200),
        [],
        [(2980, 3060)],
        0.5,
        1,
    )
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 6_000_000,
            "full_page_max_pixels": 1_000_000,
            "horizontal_overlap": 160,
            "vertical_overlap": 220,
            "cut_search_px": 260,
        }
    })
    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) > 1
    for c in chunks:
        assert c.chunk_pixels <= 6_000_000, (c.bbox, c.chunk_pixels)
        assert "over_safe_pixels" not in c.risk_flags


def test_chunk_image_path_uses_traceable_filename(tmp_path):
    image_path = tmp_path / "trace.jpg"
    Image.new("RGB", (2000, 1500), "white").save(image_path)
    profile = _profile(image_path, 2000, 1500, "table_page")
    hints = LayoutHints((0, 0, 2000, 1500), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 1_000_000,
            "safe_max_pixels": 1_500_000,
            "full_page_max_pixels": 500_000,
            "horizontal_overlap": 60,
            "vertical_overlap": 80,
        }
    })
    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) > 1
    for c in chunks:
        name = c.image_path.name
        x0, y0, x1, y1 = c.bbox
        expected = f"trace__r{c.row}_c{c.col}__x{x0}_y{y0}_w{x1 - x0}_h{y1 - y0}.jpg"
        assert name == expected
    # Manifest paths should round-trip the same traceable basename.
    manifest = json.loads((tmp_path / "chunks" / "trace" / "manifest.json").read_text())
    for entry in manifest["chunks"]:
        assert "__r" in Path(entry["image_path"]).name
        assert "_w" in Path(entry["image_path"]).name


def test_table_rowband_chunker_writes_reference_and_render_metadata(tmp_path):
    image_path = tmp_path / "rowband.jpg"
    Image.new("RGB", (2400, 1800), "white").save(image_path)
    profile = _profile(image_path, 2400, 1800, "table_page")
    hints = LayoutHints((0, 0, 2400, 1800), [(300, 340), (620, 660)], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "policy_version": "rowband_v2",
            "full_page_reference_max_pixels": 800_000,
            "row_band_target_pixels": 300_000,
            "row_band_safe_pixels": 400_000,
            "min_row_band_height": 500,
            "allow_horizontal_split": False,
        }
    })

    chunks = TableGridChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) > 2
    assert chunks[0].variant_kind == "full_page_reference"
    assert chunks[0].row == -1
    assert chunks[0].sent_width * chunks[0].sent_height <= 800_000
    assert all(chunk.variant_kind in {"full_page_reference", "table_crop"} for chunk in chunks)
    assert any(chunk.row_band == 0 for chunk in chunks[1:])

    manifest = json.loads((tmp_path / "chunks" / "rowband" / "manifest.json").read_text())
    assert manifest["chunk_policy"] == "table_rowband_v2"
    assert manifest["chunks"][0]["variant_kind"] == "full_page_reference"
    assert manifest["chunks"][0]["sent_width"] * manifest["chunks"][0]["sent_height"] <= 800_000


def test_long_chunk_image_path_uses_traceable_filename(tmp_path):
    image_path = tmp_path / "long_trace.jpg"
    Image.new("RGB", (1500, 5000), "white").save(image_path)
    profile = _profile(image_path, 1500, 5000, "long_strip")
    hints = LayoutHints((0, 0, 1500, 5000), [], [], 0.0, 1)
    chunks = LongStripChunker(
        tmp_path / "chunks", window_height=2000, overlap=200
    ).chunk(profile, hints)

    assert len(chunks) >= 2
    for c in chunks:
        name = c.image_path.name
        x0, y0, x1, y1 = c.bbox
        expected = f"long_trace__r{c.row}_c{c.col}__x{x0}_y{y0}_w{x1 - x0}_h{y1 - y0}.jpg"
        assert name == expected


def test_normal_full_page_below_full_page_max_is_not_over_safe(tmp_path):
    """Regression: a 9M normal full page (> normal.target_pixels=8M but <=
    normal.full_page_max_pixels=12M) used to be tagged over_safe_pixels
    because target_pixels was reused as the soft ceiling."""
    image_path = tmp_path / "normal_9m.jpg"
    # 3000x3000 = 9_000_000 pixels, between 8M target and 12M full_page_max.
    Image.new("RGB", (3000, 3000), "white").save(image_path)
    profile = _profile(image_path, 3000, 3000, "normal_page")
    hints = LayoutHints((0, 0, 3000, 3000), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "normal": {"full_page_max_pixels": 12_000_000, "target_pixels": 8_000_000},
    })
    chunks = PageChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) == 1
    assert chunks[0].cut_source == "full_page"
    assert "over_safe_pixels" not in chunks[0].risk_flags


def test_small_tail_flag_is_set_for_tiny_chunks(tmp_path):
    """Regression: ChunkConfig.min_pixels was defined but unused. A chunk
    smaller than min_pixels should be flagged with ``small_tail``."""
    image_path = tmp_path / "tiny.jpg"
    # Very small image well below any reasonable min_pixels threshold.
    Image.new("RGB", (40, 40), "white").save(image_path)
    profile = _profile(image_path, 40, 40, "normal_page")
    hints = LayoutHints((0, 0, 40, 40), [], [], 0.0, 1)
    cfg = ChunkConfig.from_mapping({
        "min_pixels": 4096,
        "normal": {"full_page_max_pixels": 1_000_000, "target_pixels": 500_000},
    })
    chunks = PageChunker(tmp_path / "chunks", config=cfg).chunk(profile, hints)

    assert len(chunks) == 1
    assert "small_tail" in chunks[0].risk_flags
