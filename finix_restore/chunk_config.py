from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping


@dataclass(frozen=True)
class LongChunkConfig:
    target_pixels: int = 6_000_000
    safe_max_pixels: int = 8_000_000
    max_window_height: int = 4000
    min_window_height: int = 1800
    vertical_overlap: int = 320
    blank_band_search_px: int = 360


@dataclass(frozen=True)
class TableChunkConfig:
    target_pixels: int = 6_000_000
    safe_max_pixels: int = 8_000_000
    full_page_max_pixels: int = 8_000_000
    horizontal_overlap: int = 160
    vertical_overlap: int = 220
    cut_search_px: int = 260


@dataclass(frozen=True)
class NormalChunkConfig:
    full_page_max_pixels: int = 12_000_000
    target_pixels: int = 8_000_000


# Mapping from legacy flat keys to (subsection, field).
_LEGACY_FLAT_KEYS: dict[str, tuple[str, str]] = {
    "max_chunk_pixels": ("table", "target_pixels"),
    "table_full_page_max_pixels": ("table", "full_page_max_pixels"),
    "table_horizontal_overlap": ("table", "horizontal_overlap"),
    "table_vertical_overlap": ("table", "vertical_overlap"),
    "long_window_height": ("long", "max_window_height"),
    "long_vertical_overlap": ("long", "vertical_overlap"),
}


@dataclass(frozen=True)
class ChunkConfig:
    hard_max_pixels: int = 16_777_216
    safe_max_pixels: int = 12_000_000
    min_pixels: int = 4096
    crop_margin_px: int = 24
    long: LongChunkConfig = field(default_factory=LongChunkConfig)
    table: TableChunkConfig = field(default_factory=TableChunkConfig)
    normal: NormalChunkConfig = field(default_factory=NormalChunkConfig)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ChunkConfig":
        raw = dict(raw or {})

        # Resolve flat legacy keys first, nested keys override later.
        long_kwargs: dict[str, Any] = {}
        table_kwargs: dict[str, Any] = {}
        normal_kwargs: dict[str, Any] = {}
        section_buckets = {
            "long": long_kwargs,
            "table": table_kwargs,
            "normal": normal_kwargs,
        }

        for flat_key, (section, attr) in _LEGACY_FLAT_KEYS.items():
            if flat_key in raw:
                section_buckets[section][attr] = raw[flat_key]

        nested_long = raw.get("long")
        if isinstance(nested_long, Mapping):
            long_kwargs.update(_filter_kwargs(nested_long, LongChunkConfig))

        nested_table = raw.get("table")
        if isinstance(nested_table, Mapping):
            table_kwargs.update(_filter_kwargs(nested_table, TableChunkConfig))

        nested_normal = raw.get("normal")
        if isinstance(nested_normal, Mapping):
            normal_kwargs.update(_filter_kwargs(nested_normal, NormalChunkConfig))

        top_kwargs: dict[str, Any] = {}
        for key in ("hard_max_pixels", "safe_max_pixels", "min_pixels", "crop_margin_px"):
            if key in raw:
                top_kwargs[key] = raw[key]

        return cls(
            long=LongChunkConfig(**long_kwargs),
            table=TableChunkConfig(**table_kwargs),
            normal=NormalChunkConfig(**normal_kwargs),
            **top_kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        # asdict on a dataclass already yields plain nested dicts; wrap to be
        # explicit and ensure yaml.safe_dump compatibility.
        payload = asdict(self)
        return payload

    def get(self, key: str, default: Any = None) -> Any:
        if key in _LEGACY_FLAT_KEYS:
            section, attr = _LEGACY_FLAT_KEYS[key]
            section_obj = getattr(self, section)
            return getattr(section_obj, attr)
        # Allow lookup of top-level fields by name as well, useful for
        # callers that still treat ChunkConfig as a mapping.
        for f in fields(self):
            if f.name == key:
                return getattr(self, key)
        return default


def _filter_kwargs(raw: Mapping[str, Any], cls: type) -> dict[str, Any]:
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in allowed}
