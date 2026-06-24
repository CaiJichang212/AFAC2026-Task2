import yaml

from finix_restore.chunk_config import (
    ChunkConfig,
    LongChunkConfig,
    NormalChunkConfig,
    TableChunkConfig,
)


def test_flat_legacy_keys_map_to_table_and_long():
    cfg = ChunkConfig.from_mapping(
        {
            "max_chunk_pixels": 4_000_000,
            "long_window_height": 4000,
            "table_full_page_max_pixels": 8_000_000,
            "table_horizontal_overlap": 160,
            "table_vertical_overlap": 220,
            "long_vertical_overlap": 320,
        }
    )

    assert cfg.table.target_pixels == 4_000_000
    assert cfg.long.max_window_height == 4000
    assert cfg.long.vertical_overlap == 320
    assert cfg.table.full_page_max_pixels == 8_000_000
    assert cfg.table.horizontal_overlap == 160
    assert cfg.table.vertical_overlap == 220


def test_nested_keys_take_priority_over_flat():
    cfg = ChunkConfig.from_mapping(
        {
            "max_chunk_pixels": 4_000_000,
            "table": {"target_pixels": 6_000_000},
        }
    )

    assert cfg.table.target_pixels == 6_000_000


def test_default_values_for_hard_max_and_min_pixels():
    cfg = ChunkConfig.from_mapping({})

    assert cfg.hard_max_pixels == 16_777_216
    assert cfg.safe_max_pixels == 12_000_000
    assert cfg.min_pixels == 4096
    assert cfg.crop_margin_px == 24

    assert isinstance(cfg.long, LongChunkConfig)
    assert isinstance(cfg.table, TableChunkConfig)
    assert isinstance(cfg.normal, NormalChunkConfig)

    assert cfg.long.target_pixels == 6_000_000
    assert cfg.long.safe_max_pixels == 8_000_000
    assert cfg.long.max_window_height == 4000
    assert cfg.long.min_window_height == 1800
    assert cfg.long.vertical_overlap == 320
    assert cfg.long.blank_band_search_px == 360

    assert cfg.table.target_pixels == 6_000_000
    assert cfg.table.safe_max_pixels == 8_000_000
    assert cfg.table.full_page_max_pixels == 8_000_000
    assert cfg.table.horizontal_overlap == 160
    assert cfg.table.vertical_overlap == 220
    assert cfg.table.cut_search_px == 260

    assert cfg.normal.full_page_max_pixels == 12_000_000
    assert cfg.normal.target_pixels == 8_000_000


def test_to_dict_returns_plain_nested_dict_yaml_safe():
    cfg = ChunkConfig.from_mapping({"table": {"target_pixels": 3_000_000}})

    payload = cfg.to_dict()

    assert isinstance(payload, dict)
    assert isinstance(payload["long"], dict)
    assert isinstance(payload["table"], dict)
    assert isinstance(payload["normal"], dict)
    assert payload["table"]["target_pixels"] == 3_000_000

    rendered = yaml.safe_dump(payload)
    assert "target_pixels: 3000000" in rendered


def test_table_v2_mapping_reads_new_policy_fields():
    cfg = ChunkConfig.from_mapping(
        {
            "table": {
                "policy_version": "rowband_v2",
                "full_page_reference_max_pixels": 14_000_000,
                "row_band_target_pixels": 8_000_000,
                "row_band_safe_pixels": 12_000_000,
                "min_crop_coverage": 0.55,
                "preserve_full_width": True,
                "allow_horizontal_split": True,
                "anchor_left_px": 640,
            }
        }
    )

    assert cfg.table.policy_version == "rowband_v2"
    assert cfg.table.full_page_reference_max_pixels == 14_000_000
    assert cfg.table.row_band_target_pixels == 8_000_000
    assert cfg.table.row_band_safe_pixels == 12_000_000
    assert cfg.table.min_crop_coverage == 0.55
    assert cfg.table.preserve_full_width is True
    assert cfg.table.allow_horizontal_split is True
    assert cfg.table.anchor_left_px == 640


def test_table_v2_defaults_are_stable_and_serializable():
    cfg = ChunkConfig.from_mapping({})

    assert cfg.table.policy_version == "grid_v2"
    assert cfg.table.full_page_reference_max_pixels == 14_000_000
    assert cfg.table.row_band_target_pixels == 8_000_000
    assert cfg.table.row_band_safe_pixels == 12_000_000
    assert cfg.table.min_crop_coverage == 0.55
    assert cfg.table.preserve_full_width is True
    assert cfg.table.allow_horizontal_split is True
    assert cfg.table.anchor_left_px == 640

    payload = cfg.to_dict()
    assert payload["table"]["policy_version"] == "grid_v2"
    assert payload["table"]["full_page_reference_max_pixels"] == 14_000_000
    assert payload["table"]["row_band_target_pixels"] == 8_000_000
    assert payload["table"]["row_band_safe_pixels"] == 12_000_000
    assert payload["table"]["anchor_left_px"] == 640


def test_legacy_flat_key_lookup_via_get_for_backwards_compat():
    cfg = ChunkConfig.from_mapping(
        {
            "max_chunk_pixels": 12_000_000,
            "table_full_page_max_pixels": 16_000_000,
            "long_window_height": 4000,
            "long_vertical_overlap": 320,
            "table_horizontal_overlap": 160,
            "table_vertical_overlap": 220,
        }
    )

    assert cfg.get("max_chunk_pixels") == 12_000_000
    assert cfg.get("table_full_page_max_pixels") == 16_000_000
    assert cfg.get("long_window_height") == 4000
    assert cfg.get("long_vertical_overlap") == 320
    assert cfg.get("table_horizontal_overlap") == 160
    assert cfg.get("table_vertical_overlap") == 220
    assert cfg.get("does_not_exist", 7) == 7
