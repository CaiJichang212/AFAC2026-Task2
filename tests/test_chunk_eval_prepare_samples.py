from __future__ import annotations

import csv
from pathlib import Path

from scripts.chunk_eval.prepare_samples import prepare_samples, select_samples


def _write_profile(path: Path) -> None:
    rows = []
    for subset in ("long", "table"):
        for index, pixels in enumerate([10, 20, 30, 40, 50], start=1):
            rows.append(
                {
                    "subset": subset,
                    "file_name": f"{subset}_{index}.png",
                    "width": "10",
                    "height": str(pixels),
                    "pixels": str(pixels),
                    "aspect": "1.0000",
                    "doc_type": "long_strip" if subset == "long" else "table_page",
                    "risk_level": "low",
                    "pixel_bucket": f"p{index:03d}",
                }
            )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_select_samples_is_deterministic_and_balanced(tmp_path: Path):
    profile = tmp_path / "profile.csv"
    _write_profile(profile)

    selected = select_samples(profile, per_subset=3)

    assert [row["subset"] for row in selected].count("long") == 3
    assert [row["subset"] for row in selected].count("table") == 3
    assert selected == select_samples(profile, per_subset=3)
    assert all(row["selected_reason"] for row in selected)


def test_prepare_samples_creates_manifest_and_links(tmp_path: Path):
    profile = tmp_path / "profile.csv"
    _write_profile(profile)
    long_dir = tmp_path / "long_src"
    table_dir = tmp_path / "table_src"
    for subset_dir, subset in ((long_dir, "long"), (table_dir, "table")):
        subset_dir.mkdir()
        for index in range(1, 6):
            (subset_dir / f"{subset}_{index}.png").write_bytes(b"fake")

    manifest = tmp_path / "sample_manifest.csv"
    out_root = tmp_path / "samples"
    prepare_samples(profile, {"long": long_dir, "table": table_dir}, out_root, manifest, per_subset=2)

    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    assert len(rows) == 4
    assert len(list((out_root / "long" / "images").iterdir())) == 2
    assert len(list((out_root / "table" / "images").iterdir())) == 2


def test_prepare_samples_with_relative_sources_creates_usable_links(tmp_path: Path, monkeypatch):
    profile = tmp_path / "profile.csv"
    _write_profile(profile)
    long_dir = tmp_path / "long_src"
    table_dir = tmp_path / "table_src"
    for subset_dir, subset in ((long_dir, "long"), (table_dir, "table")):
        subset_dir.mkdir()
        for index in range(1, 6):
            (subset_dir / f"{subset}_{index}.png").write_bytes(b"fake")

    monkeypatch.chdir(tmp_path)
    prepare_samples(
        Path("profile.csv"),
        {"long": Path("long_src"), "table": Path("table_src")},
        Path("samples"),
        Path("sample_manifest.csv"),
        per_subset=1,
    )

    long_sample = next((tmp_path / "samples" / "long" / "images").iterdir())
    table_sample = next((tmp_path / "samples" / "table" / "images").iterdir())
    assert long_sample.is_file()
    assert table_sample.is_file()
