from pathlib import Path

from finix_restore.chunk_config import ChunkConfig
from finix_restore.layout_sentry import LayoutHints
from finix_restore.models import ImageProfile
from finix_restore.table_image_policy import TableImagePolicy


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


def test_table_image_policy_falls_back_to_full_image_when_crop_coverage_is_low(tmp_path):
    profile = _profile(tmp_path / "table.png", 1000, 1000)
    hints = LayoutHints((100, 100, 300, 300), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping(
        {
            "crop_margin_px": 24,
            "table": {
                "policy_version": "rowband_v2",
                "min_crop_coverage": 0.55,
            },
        }
    )

    plan = TableImagePolicy().plan(profile, hints, cfg)

    assert plan.content_box == (0, 0, 1000, 1000)
    assert plan.crop_mode == "full_image_fallback"
    assert "low_crop_coverage" in plan.warnings


def test_table_image_policy_keeps_expanded_crop_when_coverage_is_sufficient(tmp_path):
    profile = _profile(tmp_path / "table.png", 1000, 1000)
    hints = LayoutHints((100, 100, 900, 900), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping(
        {
            "crop_margin_px": 24,
            "table": {
                "policy_version": "rowband_v2",
                "min_crop_coverage": 0.55,
            },
        }
    )

    plan = TableImagePolicy().plan(profile, hints, cfg)

    assert plan.content_box == (76, 76, 924, 924)
    assert plan.crop_mode == "content_crop"
    assert plan.warnings == ()


def test_table_image_policy_scales_full_page_reference_to_pixel_budget(tmp_path):
    profile = _profile(tmp_path / "table.png", 6000, 4000)
    hints = LayoutHints((0, 0, 6000, 4000), [], [], 0.5, 1)
    cfg = ChunkConfig.from_mapping(
        {
            "table": {
                "policy_version": "rowband_v2",
                "full_page_reference_max_pixels": 6_000_000,
            }
        }
    )

    plan = TableImagePolicy().plan(profile, hints, cfg)

    assert plan.reference is not None
    assert plan.reference.kind == "full_page_reference"
    assert plan.reference.source_bbox == (0, 0, 6000, 4000)
    assert plan.reference.sent_width == 3000
    assert plan.reference.sent_height == 2000
    assert plan.reference.scale == 0.5
