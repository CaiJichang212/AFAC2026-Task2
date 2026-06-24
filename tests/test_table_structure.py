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
