from pathlib import Path

from finix_restore.chunk_config import ChunkConfig
from finix_restore.layout_sentry import LayoutHints
from finix_restore.models import ImageProfile
from finix_restore.table_structure import TableStructurePlanner


def _profile(path: Path, width: int, height: int) -> ImageProfile:
    return ImageProfile(
        file_name=path.name,
        path=path,
        width=width,
        height=height,
        pixels=width * height,
        aspect=max(width, height) / min(width, height),
        doc_type="table_page",
        risk_level="low",
    )


def test_table_structure_planner_uses_full_page_for_small_table(tmp_path):
    path = tmp_path / "small_table.png"
    path.write_bytes(b"")
    profile = _profile(path, 2000, 2000)
    hints = LayoutHints((0, 0, 2000, 2000), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "target_pixels": 6_000_000,
            "safe_max_pixels": 8_000_000,
            "full_page_max_pixels": 8_000_000,
        }
    })

    plan = TableStructurePlanner().plan(profile, hints, cfg)

    assert plan.policy == "table_structure_v1"
    assert plan.content_box == (0, 0, 2000, 2000)
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.base_bbox == (0, 0, 2000, 2000)
    assert entry.crop_bbox == (0, 0, 2000, 2000)
    assert entry.cut_source == "full_page"
    assert all(e.crop_bbox[0] <= e.base_bbox[0] for e in plan.entries)


def test_table_structure_planner_splits_large_table_within_safe_budget(tmp_path):
    path = tmp_path / "large_table.png"
    path.write_bytes(b"")
    profile = _profile(path, 6000, 4200)
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

    plan = TableStructurePlanner().plan(profile, hints, cfg)

    assert plan.policy == "table_structure_v1"
    assert len(plan.entries) > 1
    assert all((e.crop_bbox[2] - e.crop_bbox[0]) * (e.crop_bbox[3] - e.crop_bbox[1]) <= 6_000_000 for e in plan.entries)
    assert all(e.crop_bbox[0] <= e.base_bbox[0] for e in plan.entries)
    assert all(e.crop_bbox[1] <= e.base_bbox[1] for e in plan.entries)
    assert any(e.cut_source == "fixed_cut" for e in plan.entries)


def test_table_structure_planner_marks_blank_band_cuts(tmp_path):
    path = tmp_path / "band_table.png"
    path.write_bytes(b"")
    profile = _profile(path, 6000, 4200)
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

    plan = TableStructurePlanner().plan(profile, hints, cfg)

    assert plan.policy == "table_structure_v1"
    assert any(entry.cut_source == "blank_band" for entry in plan.entries)


def test_table_structure_planner_rowband_v2_prefers_full_width_bands_and_reference(tmp_path):
    path = tmp_path / "rowband_table.png"
    path.write_bytes(b"")
    profile = _profile(path, 12000, 9000)
    hints = LayoutHints((0, 0, 12000, 9000), [(980, 1040), (2040, 2100)], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "policy_version": "rowband_v2",
            "full_page_reference_max_pixels": 6_000_000,
            "row_band_target_pixels": 8_000_000,
            "row_band_safe_pixels": 12_000_000,
            "preserve_full_width": True,
            "allow_horizontal_split": True,
        }
    })

    plan = TableStructurePlanner().plan(profile, hints, cfg)

    assert plan.policy == "table_structure_rowband_v2"
    assert plan.entries[0].variant_kind == "full_page_reference"
    assert plan.entries[0].row_band == -1
    assert plan.entries[0].col_band == 0
    band_entries = [entry for entry in plan.entries if entry.row_band >= 0]
    assert len(band_entries) > 1
    assert all(entry.cols == 1 for entry in band_entries)
    assert all(entry.variant_kind == "table_crop" for entry in band_entries)
    assert all(entry.sent_width is not None and entry.sent_height is not None for entry in band_entries)
    assert all(entry.sent_width * entry.sent_height <= cfg.table.row_band_safe_pixels for entry in band_entries)


def test_table_structure_planner_rowband_v2_can_disable_horizontal_split(tmp_path):
    path = tmp_path / "rowband_no_split.png"
    path.write_bytes(b"")
    profile = _profile(path, 12000, 9000)
    hints = LayoutHints((0, 0, 12000, 9000), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "policy_version": "rowband_v2",
            "row_band_target_pixels": 4_000_000,
            "row_band_safe_pixels": 6_000_000,
            "allow_horizontal_split": False,
        }
    })

    plan = TableStructurePlanner().plan(profile, hints, cfg)

    assert all("horizontal_split" not in entry.risk_flags for entry in plan.entries)
    assert all(entry.anchor_bbox is None for entry in plan.entries)


def test_rowband_v2_handles_very_wide_image_without_explosion(tmp_path):
    """Regression: 超大宽图 target_height 塌缩导致切片爆炸/guard 崩溃.

    旧逻辑下 content_width=40000 时 target_height=150 < vertical_overlap,
    每轮只推进 1px, 把图切成上万条带并触发 iteration guard.
    修复后 min_row_band_height 给 target_height 设下限, 切片数保持合理.
    """
    from PIL import Image
    wide = 40000
    tall = 50000
    image_path = tmp_path / "huge_wide.jpg"
    Image.new("RGB", (wide, tall), "white").save(image_path)
    profile = _profile(image_path, wide, tall)
    hints = LayoutHints((0, 0, wide, tall), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping({
        "table": {
            "policy_version": "rowband_v2",
            "row_band_target_pixels": 6_000_000,
            "row_band_safe_pixels": 10_000_000,
            "allow_horizontal_split": True,
        }
    })
    plan = TableStructurePlanner().plan(profile, hints, cfg)
    assert len(plan.entries) < 100, f"too many bands: {len(plan.entries)}"
