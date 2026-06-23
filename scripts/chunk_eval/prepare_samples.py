from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


def _read_rows(profile_csv: Path) -> list[dict[str, str]]:
    with Path(profile_csv).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _pick_indices(count: int, wanted: int) -> list[int]:
    if count <= 0 or wanted <= 0:
        return []
    if wanted >= count:
        return list(range(count))
    if wanted == 1:
        return [count // 2]
    return sorted({round(i * (count - 1) / (wanted - 1)) for i in range(wanted)})


def select_samples(profile_csv: Path, per_subset: int) -> list[dict[str, str]]:
    rows = _read_rows(profile_csv)
    selected: list[dict[str, str]] = []
    for subset in sorted({row["subset"] for row in rows}):
        subset_rows = sorted(
            [row for row in rows if row["subset"] == subset],
            key=lambda row: (int(row["pixels"]), row["file_name"]),
        )
        for rank, index in enumerate(_pick_indices(len(subset_rows), per_subset), start=1):
            row = dict(subset_rows[index])
            row["selected_reason"] = f"pixel_quantile_rank_{rank}_of_{per_subset}"
            selected.append(row)
    return sorted(selected, key=lambda row: (row["subset"], int(row["pixels"]), row["file_name"]))


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def prepare_samples(
    profile_csv: Path,
    source_dirs: dict[str, Path],
    out_root: Path,
    manifest_path: Path,
    per_subset: int,
) -> list[dict[str, str]]:
    selected = select_samples(profile_csv, per_subset=per_subset)
    for row in selected:
        subset = row["subset"]
        src = Path(source_dirs[subset]) / row["file_name"]
        dst = Path(out_root) / subset / "images" / row["file_name"]
        if not src.exists():
            raise FileNotFoundError(src)
        _link_or_copy(src, dst)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(selected[0]) if selected else [
        "subset",
        "file_name",
        "width",
        "height",
        "pixels",
        "aspect",
        "doc_type",
        "risk_level",
        "pixel_bucket",
        "selected_reason",
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare deterministic sample image dirs for chunking experiments")
    parser.add_argument("--profile_csv", required=True, type=Path)
    parser.add_argument("--long_dir", required=True, type=Path)
    parser.add_argument("--table_dir", required=True, type=Path)
    parser.add_argument("--out_root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--per_subset", type=int, default=10)
    args = parser.parse_args(argv)

    selected = prepare_samples(
        args.profile_csv,
        {"long": args.long_dir, "table": args.table_dir},
        args.out_root,
        args.manifest,
        args.per_subset,
    )
    print(f"selected {len(selected)} files -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
