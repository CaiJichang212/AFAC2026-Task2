# Chunking Evaluation Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and execute a reproducible training-set experiment workflow that compares image chunking budgets, scores FinixDoc-VL outputs on train long/table data, diagnoses score loss, and writes the next-stage optimization report.

**Architecture:** Keep the production `finix_restore` pipeline unchanged unless a test reveals a blocking bug. Add small experiment-only scripts under `scripts/chunk_eval/` for profiling, sample selection, submission validation, metrics summarization, and Markdown reporting; all run artifacts stay under `outputs/chunk_eval/`. Use the existing `finix_restore.cli` for prediction and `finix_restore.eval.cli` for official-aligned scoring.

**Tech Stack:** Python 3.12, standard library `csv/json/pathlib/statistics/shutil`, Pillow through existing `ImageProfiler`, existing `finix_restore` modules, Bash, pytest.

---

## 0. Scope And Constraints

Spec source:

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/superpowers/specs/2026-06-23-chunking-evaluation-design.md`

Hard constraints:

- Do not modify `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/data`.
- Do not read, print, or commit `.env` secrets.
- Do not call any model/API except FinixDoc-VL through the existing client.
- Do not hard-code train/A/B file names into algorithmic behavior.
- Do not submit `outputs/` artifacts to git.

Implementation outputs:

- New experiment scripts: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/`
- New tests: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_*.py`
- Run artifacts: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/`
- Final report: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/final_report.md`

## 1. File Structure

Create:

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/__init__.py`
  - Marks the experiment helpers as importable for tests.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/baseline_5m.yaml`
  - Mirrors current default chunk budgets for a named baseline.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/table_4m_safe.yaml`
  - Keeps long at 6M and lowers table to 4M/6M.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/balanced_6m.yaml`
  - Uses table 6M/8M for request-count comparison.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/long_4m_table_4m.yaml`
  - Conservative all-around 4M profile.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/large_8m_probe.yaml`
  - Dry-run/probe-only larger budget.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/profile_train.py`
  - Writes S0 `train_profile.csv` and `bucket_summary.csv`.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/prepare_samples.py`
  - Selects deterministic representative samples and creates output sample dirs by symlink or copy fallback.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py`
  - Validates CSV schema, row count, duplicate names, and readability.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_metrics.py`
  - Combines long/table scorer JSON and API logs into compact Markdown/CSV summaries.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/write_final_report.py`
  - Writes `outputs/chunk_eval/final_report.md` from dry-run, S2, and S3 summaries.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/run_dry_run_matrix.sh`
  - Runs S1 dry-run for all candidate configs on train long/table.
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_profile.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_prepare_samples.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_validate_submission.py`
- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_metrics.py`

Modify:

- `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`
  - Append a short pointer to `outputs/chunk_eval/final_report.md` and the spec/plan paths after experiments complete.

## 2. Task 1: Add Experiment Configs And Script Package

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/__init__.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/baseline_5m.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/table_4m_safe.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/balanced_6m.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/long_4m_table_4m.yaml`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/large_8m_probe.yaml`

- [ ] **Step 1: Create script package marker**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/__init__.py`:

```python
"""Experiment helpers for AFAC Task2 chunking evaluation."""
```

- [ ] **Step 2: Create `baseline_5m.yaml`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/baseline_5m.yaml`:

```yaml
api:
  url: "${FINIX_API_URL}"
  timeout_seconds: 360
  max_retries: 3
  concurrency: 2
  per_user_concurrency: 1
chunk:
  hard_max_pixels: 16777216
  safe_max_pixels: 12000000
  min_pixels: 4096
  crop_margin_px: 24
  long:
    target_pixels: 6000000
    safe_max_pixels: 8000000
    max_window_height: 4000
    min_window_height: 1800
    vertical_overlap: 320
    blank_band_search_px: 360
  table:
    target_pixels: 5000000
    safe_max_pixels: 7000000
    full_page_max_pixels: 8000000
    horizontal_overlap: 160
    vertical_overlap: 220
    cut_search_px: 260
  normal:
    full_page_max_pixels: 12000000
    target_pixels: 8000000
merge:
  dedup_window_chars_long: 1200
  dedup_window_chars_table: 600
  dedup_similarity_threshold: 0.88
quality:
  max_duplication_ratio: 0.18
  max_api_failure_ratio: 0.20
  max_reruns_per_file: 2
runtime:
  image_concurrency: 1
```

- [ ] **Step 3: Create `table_4m_safe.yaml`**

Copy `baseline_5m.yaml` to `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/table_4m_safe.yaml` and change only:

```yaml
  table:
    target_pixels: 4000000
    safe_max_pixels: 6000000
```

Keep all other keys identical to `baseline_5m.yaml`.

- [ ] **Step 4: Create `balanced_6m.yaml`**

Copy `baseline_5m.yaml` to `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/balanced_6m.yaml` and change only:

```yaml
  table:
    target_pixels: 6000000
    safe_max_pixels: 8000000
```

Keep all other keys identical to `baseline_5m.yaml`.

- [ ] **Step 5: Create `long_4m_table_4m.yaml`**

Copy `baseline_5m.yaml` to `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/long_4m_table_4m.yaml` and change:

```yaml
  long:
    target_pixels: 4000000
    safe_max_pixels: 6000000
  table:
    target_pixels: 4000000
    safe_max_pixels: 6000000
```

Keep overlap, retry, merge, quality, and runtime keys identical to `baseline_5m.yaml`.

- [ ] **Step 6: Create `large_8m_probe.yaml`**

Copy `baseline_5m.yaml` to `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/configs/large_8m_probe.yaml` and change:

```yaml
  long:
    target_pixels: 8000000
    safe_max_pixels: 10000000
  table:
    target_pixels: 8000000
    safe_max_pixels: 12000000
```

Keep all other keys identical to `baseline_5m.yaml`.

- [ ] **Step 7: Verify configs load**

Run:

```bash
for cfg in scripts/chunk_eval/configs/*.yaml; do
  python - <<'PY' "${cfg}"
from pathlib import Path
from types import SimpleNamespace
from finix_restore.config import load_config
args = SimpleNamespace(
    config=__import__("sys").argv[1],
    dry_run=True,
    input_dir=["data/AFAC 训练数据集/finixdocbench_huge_long_100/images"],
    output_csv="outputs/chunk_eval/_config_check/submission.csv",
    work_dir="outputs/chunk_eval/_config_check",
    resume=True,
    force_api=False,
    limit=None,
    limit_per_dir=1,
    image_concurrency=None,
)
cfg = load_config(args)
print(Path(args.config).name, cfg.chunk.long.target_pixels, cfg.chunk.table.target_pixels)
PY
done
```

Expected: each config name prints once; no stack trace; no secret value printed.

- [ ] **Step 8: Commit**

Run:

```bash
git add scripts/chunk_eval/__init__.py scripts/chunk_eval/configs
git commit -m "chore(exp): add chunk evaluation config matrix"
```

## 3. Task 2: Implement S0 Training Profile Script

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/profile_train.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_profile.py`

- [ ] **Step 1: Write tests**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_profile.py`:

```python
from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from scripts.chunk_eval.profile_train import build_profiles, write_profile_outputs


def _make_image(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)


def test_build_profiles_writes_expected_columns(tmp_path: Path):
    long_dir = tmp_path / "long"
    table_dir = tmp_path / "table"
    _make_image(long_dir / "long_a.png", (100, 1200))
    _make_image(table_dir / "table_a.png", (4000, 4000))

    rows = build_profiles({"long": long_dir, "table": table_dir})

    assert [row["subset"] for row in rows] == ["long", "table"]
    assert rows[0]["file_name"] == "long_a.png"
    assert rows[0]["doc_type"] == "long_strip"
    assert rows[1]["doc_type"] == "table_page"
    assert "pixel_bucket" in rows[0]


def test_write_profile_outputs_creates_csvs(tmp_path: Path):
    rows = [
        {
            "subset": "long",
            "file_name": "a.png",
            "width": 100,
            "height": 1200,
            "pixels": 120000,
            "aspect": "12.0000",
            "doc_type": "long_strip",
            "risk_level": "low",
            "pixel_bucket": "p000_p020",
        },
        {
            "subset": "table",
            "file_name": "b.png",
            "width": 4000,
            "height": 4000,
            "pixels": 16000000,
            "aspect": "1.0000",
            "doc_type": "normal_page",
            "risk_level": "medium",
            "pixel_bucket": "p080_p100",
        },
    ]

    write_profile_outputs(rows, tmp_path)

    profile_csv = tmp_path / "train_profile.csv"
    summary_csv = tmp_path / "bucket_summary.csv"
    assert profile_csv.exists()
    assert summary_csv.exists()
    profile_rows = list(csv.DictReader(profile_csv.open(encoding="utf-8")))
    summary_rows = list(csv.DictReader(summary_csv.open(encoding="utf-8")))
    assert len(profile_rows) == 2
    assert summary_rows[0]["subset"] == "long"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_chunk_eval_profile.py -v
```

Expected: FAIL because `scripts.chunk_eval.profile_train` does not exist.

- [ ] **Step 3: Implement `profile_train.py`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/profile_train.py`:

```python
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from finix_restore.profiler import ImageProfiler
from finix_restore.quality_gate import IMAGE_SUFFIXES


FIELDNAMES = [
    "subset",
    "file_name",
    "width",
    "height",
    "pixels",
    "aspect",
    "doc_type",
    "risk_level",
    "pixel_bucket",
]


def _list_images(path: Path) -> list[Path]:
    return sorted(
        [p for p in Path(path).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES],
        key=lambda p: p.name,
    )


def _bucket_labels(count: int) -> list[str]:
    if count <= 0:
        return []
    labels: list[str] = []
    for index in range(count):
        pct_low = int((index / count) * 100)
        pct_high = int(((index + 1) / count) * 100)
        labels.append(f"p{pct_low:03d}_p{pct_high:03d}")
    return labels


def build_profiles(subset_dirs: dict[str, Path]) -> list[dict[str, str | int]]:
    profiler = ImageProfiler()
    raw_rows: list[dict[str, str | int | float]] = []
    for subset, directory in subset_dirs.items():
        for image_path in _list_images(directory):
            profile = profiler.profile(image_path)
            raw_rows.append(
                {
                    "subset": subset,
                    "file_name": profile.file_name,
                    "width": profile.width,
                    "height": profile.height,
                    "pixels": profile.pixels,
                    "aspect": profile.aspect,
                    "doc_type": profile.doc_type,
                    "risk_level": profile.risk_level,
                }
            )

    ordered = sorted(raw_rows, key=lambda row: (int(row["pixels"]), str(row["subset"]), str(row["file_name"])))
    labels = _bucket_labels(len(ordered))
    bucket_by_key = {
        (row["subset"], row["file_name"]): labels[index]
        for index, row in enumerate(ordered)
    }

    result: list[dict[str, str | int]] = []
    for row in sorted(raw_rows, key=lambda item: (str(item["subset"]), str(item["file_name"]))):
        result.append(
            {
                "subset": str(row["subset"]),
                "file_name": str(row["file_name"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "pixels": int(row["pixels"]),
                "aspect": f"{float(row['aspect']):.4f}",
                "doc_type": str(row["doc_type"]),
                "risk_level": str(row["risk_level"]),
                "pixel_bucket": bucket_by_key[(row["subset"], row["file_name"])],
            }
        )
    return result


def write_profile_outputs(rows: list[dict[str, str | int]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = out_dir / "train_profile.csv"
    with profile_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    counters: Counter[tuple[str, str, str, str]] = Counter()
    for row in rows:
        counters[
            (
                str(row["subset"]),
                str(row["doc_type"]),
                str(row["risk_level"]),
                str(row["pixel_bucket"]),
            )
        ] += 1

    summary_path = out_dir / "bucket_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["subset", "doc_type", "risk_level", "pixel_bucket", "files"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for key, count in sorted(counters.items()):
            subset, doc_type, risk_level, pixel_bucket = key
            writer.writerow(
                {
                    "subset": subset,
                    "doc_type": doc_type,
                    "risk_level": risk_level,
                    "pixel_bucket": pixel_bucket,
                    "files": count,
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile AFAC Task2 train images for chunking experiments")
    parser.add_argument("--long_dir", required=True, type=Path)
    parser.add_argument("--table_dir", required=True, type=Path)
    parser.add_argument("--out_dir", required=True, type=Path)
    args = parser.parse_args(argv)

    rows = build_profiles({"long": args.long_dir, "table": args.table_dir})
    write_profile_outputs(rows, args.out_dir)
    print(f"wrote {len(rows)} profile rows -> {args.out_dir / 'train_profile.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_chunk_eval_profile.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/chunk_eval/profile_train.py tests/test_chunk_eval_profile.py
git commit -m "feat(exp): add train image profiling helper"
```

## 4. Task 3: Implement Deterministic Sample Selection

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/prepare_samples.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_prepare_samples.py`

- [ ] **Step 1: Write tests**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_prepare_samples.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_chunk_eval_prepare_samples.py -v
```

Expected: FAIL because `prepare_samples.py` does not exist.

- [ ] **Step 3: Implement `prepare_samples.py`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/prepare_samples.py`:

```python
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
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_chunk_eval_prepare_samples.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/chunk_eval/prepare_samples.py tests/test_chunk_eval_prepare_samples.py
git commit -m "feat(exp): add deterministic sample preparation"
```

## 5. Task 4: Implement Submission Validation

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_validate_submission.py`

- [ ] **Step 1: Write tests**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_validate_submission.py`:

```python
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.chunk_eval.validate_submission import validate_submission


def _write_csv(path: Path, rows: list[tuple[str, str]], header: tuple[str, str] = ("file_name", "ground_truth")) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def test_validate_submission_accepts_valid_csv(tmp_path: Path):
    csv_path = tmp_path / "submission.csv"
    _write_csv(csv_path, [("a.png", "A"), ("b.png", "")])

    report = validate_submission(csv_path, expected_count=2)

    assert report["passed"] is True
    assert report["rows"] == 2
    assert report["empty_outputs"] == 1
    assert report["duplicate_file_names"] == []


def test_validate_submission_rejects_bad_header(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    _write_csv(csv_path, [("a.png", "A")], header=("name", "text"))

    with pytest.raises(ValueError, match="columns"):
        validate_submission(csv_path, expected_count=1)


def test_validate_submission_reports_duplicate_and_count(tmp_path: Path):
    csv_path = tmp_path / "dup.csv"
    _write_csv(csv_path, [("a.png", "A"), ("a.png", "B")])

    report = validate_submission(csv_path, expected_count=3)

    assert report["passed"] is False
    assert report["rows"] == 2
    assert report["duplicate_file_names"] == ["a.png"]
    assert "row_count_mismatch" in report["risks"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_chunk_eval_validate_submission.py -v
```

Expected: FAIL because `validate_submission.py` does not exist.

- [ ] **Step 3: Implement `validate_submission.py`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/validate_submission.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


_raise_csv_field_limit()


def validate_submission(path: Path, expected_count: int | None = None) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["file_name", "ground_truth"]:
            raise ValueError(f"CSV columns must be exactly file_name,ground_truth: {path}")
        rows = list(reader)

    names = [(row.get("file_name") or "").strip() for row in rows]
    counts = Counter(names)
    duplicates = sorted(name for name, count in counts.items() if name and count > 1)
    empty_names = sum(1 for name in names if not name)
    empty_outputs = sum(1 for row in rows if not (row.get("ground_truth") or "").strip())

    risks: list[str] = []
    if expected_count is not None and len(rows) != expected_count:
        risks.append("row_count_mismatch")
    if duplicates:
        risks.append("duplicate_file_names")
    if empty_names:
        risks.append("empty_file_names")

    return {
        "passed": not risks,
        "rows": len(rows),
        "expected_count": expected_count,
        "duplicate_file_names": duplicates,
        "empty_file_names": empty_names,
        "empty_outputs": empty_outputs,
        "risks": risks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate AFAC Task2 submission CSV")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--expected_count", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = validate_submission(args.csv, args.expected_count)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_chunk_eval_validate_submission.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/chunk_eval/validate_submission.py tests/test_chunk_eval_validate_submission.py
git commit -m "feat(exp): add submission validation helper"
```

## 6. Task 5: Implement Metric Summaries And Report Writer

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_metrics.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/write_final_report.py`
- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_metrics.py`

- [ ] **Step 1: Write tests**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/tests/test_chunk_eval_summarize_metrics.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.chunk_eval.summarize_metrics import load_metric_summary, render_metric_table
from scripts.chunk_eval.write_final_report import write_report


def test_load_metric_summary_extracts_top_worst(tmp_path: Path):
    metrics = {
        "file_count": 2,
        "mean_text_edit": 0.2,
        "mean_table_teds": 50.0,
        "mean_read_order_edit": 0.3,
        "mean_overall": 66.67,
        "table_sample_count": 1,
        "files": [
            {"file_name": "good.png", "overall": 90.0, "text_edit": 0.1, "table_teds": None, "read_order_edit": 0.1},
            {"file_name": "bad.png", "overall": 20.0, "text_edit": 0.8, "table_teds": 10.0, "read_order_edit": 0.7},
        ],
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics), encoding="utf-8")

    summary = load_metric_summary("long", path, top_n=1)

    assert summary["subset"] == "long"
    assert summary["file_count"] == 2
    assert summary["worst_files"][0]["file_name"] == "bad.png"


def test_render_metric_table_outputs_markdown():
    rows = [
        {
            "subset": "long",
            "file_count": 2,
            "mean_text_edit": 0.2,
            "mean_table_teds": 50.0,
            "mean_read_order_edit": 0.3,
            "mean_overall": 66.67,
            "table_sample_count": 1,
            "worst_files": [],
        }
    ]

    markdown = render_metric_table(rows)

    assert "| subset | files | Text Edit | Table TEDS | Read Order Edit | Overall |" in markdown
    assert "| long | 2 | 0.2000 | 50.00 | 0.3000 | 66.67 |" in markdown


def test_write_report_includes_sections(tmp_path: Path):
    out = tmp_path / "final_report.md"
    write_report(
        out,
        title="Report",
        dry_run_summary="dry run text",
        s2_summary="s2 text",
        s3_summary="s3 text",
        findings=["API failures dominate", "Table TEDS remains low"],
        next_steps=["Lower table target to 4M"],
    )

    text = out.read_text(encoding="utf-8")
    assert "# Report" in text
    assert "## 失分原因定位" in text
    assert "- API failures dominate" in text
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_chunk_eval_summarize_metrics.py -v
```

Expected: FAIL because summary modules do not exist.

- [ ] **Step 3: Implement `summarize_metrics.py`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/summarize_metrics.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_metric_summary(subset: str, metrics_path: Path, top_n: int = 10) -> dict:
    data = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    files = sorted(data.get("files", []), key=lambda row: float(row.get("overall", 0.0)))
    return {
        "subset": subset,
        "file_count": int(data.get("file_count", 0)),
        "mean_text_edit": float(data.get("mean_text_edit", 0.0)),
        "mean_table_teds": float(data.get("mean_table_teds", 0.0)),
        "mean_read_order_edit": float(data.get("mean_read_order_edit", 0.0)),
        "mean_overall": float(data.get("mean_overall", 0.0)),
        "table_sample_count": int(data.get("table_sample_count", 0)),
        "worst_files": files[:top_n],
    }


def render_metric_table(rows: list[dict]) -> str:
    lines = [
        "| subset | files | Text Edit | Table TEDS | Read Order Edit | Overall | table samples |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {subset} | {file_count} | {mean_text_edit:.4f} | {mean_table_teds:.2f} | "
            "{mean_read_order_edit:.4f} | {mean_overall:.2f} | {table_sample_count} |".format(**row)
        )
    return "\n".join(lines)


def render_worst_files(rows: list[dict]) -> str:
    lines = [
        "| subset | file_name | Overall | Text Edit | Table TEDS | Read Order Edit |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        for item in row["worst_files"]:
            table_teds = item.get("table_teds")
            table_text = "" if table_teds is None else f"{float(table_teds):.2f}"
            lines.append(
                "| {subset} | {file_name} | {overall:.2f} | {text_edit:.4f} | {table_teds} | {read_order_edit:.4f} |".format(
                    subset=row["subset"],
                    file_name=item.get("file_name", ""),
                    overall=float(item.get("overall", 0.0)),
                    text_edit=float(item.get("text_edit", 0.0)),
                    table_teds=table_text,
                    read_order_edit=float(item.get("read_order_edit", 0.0)),
                )
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize scorer JSON files into Markdown")
    parser.add_argument("--metric", action="append", nargs=2, metavar=("SUBSET", "JSON"), required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--top_n", type=int, default=10)
    args = parser.parse_args(argv)

    summaries = [load_metric_summary(subset, Path(path), args.top_n) for subset, path in args.metric]
    markdown = "\n\n".join(
        [
            "## 指标汇总",
            render_metric_table(summaries),
            "## 最差样本",
            render_worst_files(summaries),
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement `write_final_report.py`**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/write_final_report.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- 无"


def _read_optional(path: Path | None) -> str:
    if path is None:
        return "未提供。"
    return Path(path).read_text(encoding="utf-8") if Path(path).exists() else f"文件不存在：{path}"


def write_report(
    out: Path,
    title: str,
    dry_run_summary: str,
    s2_summary: str,
    s3_summary: str,
    findings: list[str],
    next_steps: list[str],
) -> None:
    text = f"""# {title}

## 实验摘要

本报告汇总训练集切图预算实验、FinixDoc-VL API 小样本消融、训练集扩大测评和下一阶段优化建议。

## Dry-run 切图结果

{dry_run_summary}

## API 小样本消融结果

{s2_summary}

## 训练集测评结果

{s3_summary}

## 失分原因定位

{_bullets(findings)}

## 下一阶段优化计划

{_bullets(next_steps)}

## 复现入口

- 设计文档：`docs/superpowers/specs/2026-06-23-chunking-evaluation-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-23-chunking-evaluation-execution.md`
- 运行产物：`outputs/chunk_eval/`
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write final Markdown report for chunking evaluation")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", default="训练集切图实验与测评分析报告")
    parser.add_argument("--dry_run_md", type=Path)
    parser.add_argument("--s2_md", type=Path)
    parser.add_argument("--s3_md", type=Path)
    parser.add_argument("--finding", action="append", default=[])
    parser.add_argument("--next_step", action="append", default=[])
    args = parser.parse_args(argv)

    write_report(
        args.out,
        args.title,
        _read_optional(args.dry_run_md),
        _read_optional(args.s2_md),
        _read_optional(args.s3_md),
        args.finding,
        args.next_step,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/test_chunk_eval_summarize_metrics.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add scripts/chunk_eval/summarize_metrics.py scripts/chunk_eval/write_final_report.py tests/test_chunk_eval_summarize_metrics.py
git commit -m "feat(exp): add metric summary report helpers"
```

## 7. Task 6: Add Dry-run Matrix Runner

**Files:**

- Create: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/run_dry_run_matrix.sh`

- [ ] **Step 1: Create runner**

Create `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/scripts/chunk_eval/run_dry_run_matrix.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

OUT_ROOT="${REPO_ROOT}/outputs/chunk_eval/s1_dry_run"
CFG_ROOT="${REPO_ROOT}/scripts/chunk_eval/configs"

TRAIN_LONG="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_long_100/images"
TRAIN_TABLE="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_table_100/images"

declare -a CONFIGS=(
  "baseline_5m"
  "table_4m_safe"
  "balanced_6m"
  "long_4m_table_4m"
  "large_8m_probe"
)

for name in "${CONFIGS[@]}"; do
  cfg="${CFG_ROOT}/${name}.yaml"
  for subset in long table; do
    if [[ "${subset}" == "long" ]]; then
      input_dir="${TRAIN_LONG}"
    else
      input_dir="${TRAIN_TABLE}"
    fi
    work_dir="${OUT_ROOT}/${name}/${subset}"
    echo "=== dry-run config=${name} subset=${subset} ==="
    mkdir -p "${work_dir}"
    python -m finix_restore.cli \
      --input_dir "${input_dir}" \
      --output_csv "${work_dir}/submission.csv" \
      --work_dir "${work_dir}" \
      --config "${cfg}" \
      --dry_run
  done
done

python scripts/chunk_budget_experiment/aggregate_dry_run.py \
  --root "${OUT_ROOT}" \
  --out "${OUT_ROOT}/summary.csv"

echo "Dry-run matrix complete: ${OUT_ROOT}/summary.csv"
```

- [ ] **Step 2: Make runner executable**

Run:

```bash
chmod +x scripts/chunk_eval/run_dry_run_matrix.sh
```

- [ ] **Step 3: Syntax-check runner**

Run:

```bash
bash -n scripts/chunk_eval/run_dry_run_matrix.sh
```

Expected: exits 0.

- [ ] **Step 4: Commit**

Run:

```bash
git add scripts/chunk_eval/run_dry_run_matrix.sh
git commit -m "chore(exp): add train dry-run matrix runner"
```

## 8. Task 7: Run Unit Tests And Static Diff Check

**Files:** no source file changes unless tests fail and reveal a bug introduced in Tasks 1-6.

- [ ] **Step 1: Run experiment helper tests**

Run:

```bash
pytest tests/test_chunk_eval_profile.py \
  tests/test_chunk_eval_prepare_samples.py \
  tests/test_chunk_eval_validate_submission.py \
  tests/test_chunk_eval_summarize_metrics.py -q
```

Expected: all pass.

- [ ] **Step 2: Run existing focused regression tests**

Run:

```bash
pytest tests/test_chunk_config.py tests/test_chunkers.py tests/test_eval_scorer.py tests/test_submission.py -q
```

Expected: all pass.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 4: Commit fixes only if Step 1-3 required changes**

If any test required a code fix, commit only those changed files:

```bash
git add <changed-files>
git commit -m "fix(exp): stabilize chunk evaluation helpers"
```

Expected: no commit is needed when Steps 1-3 pass without edits.

## 9. Task 8: Execute S0 Profile

**Files:** run artifacts only under `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/s0_profile/`

- [ ] **Step 1: Run profile script**

Run:

```bash
python -m scripts.chunk_eval.profile_train \
  --long_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --table_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --out_dir outputs/chunk_eval/s0_profile
```

Expected:

- Prints `wrote 200 profile rows -> outputs/chunk_eval/s0_profile/train_profile.csv`.
- Creates `outputs/chunk_eval/s0_profile/train_profile.csv`.
- Creates `outputs/chunk_eval/s0_profile/bucket_summary.csv`.

- [ ] **Step 2: Verify row count**

Run:

```bash
python - <<'PY'
import csv
from pathlib import Path
path = Path("outputs/chunk_eval/s0_profile/train_profile.csv")
rows = list(csv.DictReader(path.open(encoding="utf-8")))
print(len(rows))
assert len(rows) == 200
assert {row["subset"] for row in rows} == {"long", "table"}
PY
```

Expected: prints `200`.

## 10. Task 9: Execute S1 Dry-run Matrix

**Files:** run artifacts only under `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/s1_dry_run/`

- [ ] **Step 1: Run dry-run matrix**

Run:

```bash
bash scripts/chunk_eval/run_dry_run_matrix.sh
```

Expected:

- Runs five configs against train long and table.
- Does not require `FINIX_API_KEY`.
- Writes `outputs/chunk_eval/s1_dry_run/summary.csv`.

- [ ] **Step 2: Verify no hard-limit chunk**

Run:

```bash
python - <<'PY'
import csv
from pathlib import Path
path = Path("outputs/chunk_eval/s1_dry_run/summary.csv")
rows = list(csv.DictReader(path.open(encoding="utf-8")))
assert rows, "dry-run summary is empty"
bad = [row for row in rows if int(row["over_hard_total"]) > 0]
print(f"rows={len(rows)} over_hard_rows={len(bad)}")
assert not bad, bad
PY
```

Expected: `over_hard_rows=0`.

- [ ] **Step 3: Choose S2 candidates**

Read `outputs/chunk_eval/s1_dry_run/summary.csv` and select at least two candidates for S2:

- Always include `baseline_5m`.
- Include `table_4m_safe` if it reduces `over_safe_total` or max table pixels.
- Include `balanced_6m` if it materially reduces table chunk count without hard-limit risk.
- Do not include `large_8m_probe` in full API S2 unless dry-run shows no `over_safe_total` and chunk count reduction is large enough to justify timeout risk.

Record the chosen candidate names in `outputs/chunk_eval/s2_api_ablation/candidates.txt`, one per line.

## 11. Task 10: Prepare S2 Samples

**Files:** run artifacts under `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/s2_api_ablation/`

- [ ] **Step 1: Prepare deterministic sample dirs**

Run:

```bash
python -m scripts.chunk_eval.prepare_samples \
  --profile_csv outputs/chunk_eval/s0_profile/train_profile.csv \
  --long_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --table_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --out_root outputs/chunk_eval/s2_api_ablation/samples \
  --manifest outputs/chunk_eval/s2_api_ablation/sample_manifest.csv \
  --per_subset 10
```

Expected:

- Prints `selected 20 files -> outputs/chunk_eval/s2_api_ablation/sample_manifest.csv`.
- Creates `samples/long/images` with 10 files.
- Creates `samples/table/images` with 10 files.

- [ ] **Step 2: Verify sample count**

Run:

```bash
python - <<'PY'
import csv
from pathlib import Path
rows = list(csv.DictReader(Path("outputs/chunk_eval/s2_api_ablation/sample_manifest.csv").open(encoding="utf-8")))
print(len(rows), sorted({row["subset"] for row in rows}))
assert len(rows) == 20
assert [row["subset"] for row in rows].count("long") == 10
assert [row["subset"] for row in rows].count("table") == 10
PY
```

Expected: prints `20 ['long', 'table']`.

## 12. Task 11: Execute S2 API Small-sample Ablation

**Files:** run artifacts under `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/s2_api_ablation/<candidate>/`

This task calls FinixDoc-VL. Before running, verify `.env` exists only by checking required environment variables through `load_config`; do not print secret values.

- [ ] **Step 1: Run predictions for each candidate**

For each candidate listed in `outputs/chunk_eval/s2_api_ablation/candidates.txt`, run:

```bash
candidate="baseline_5m"
cfg="scripts/chunk_eval/configs/${candidate}.yaml"

python -m finix_restore.cli \
  --input_dir outputs/chunk_eval/s2_api_ablation/samples/long/images \
  --output_csv "outputs/chunk_eval/s2_api_ablation/${candidate}/long_submission.csv" \
  --work_dir "outputs/chunk_eval/s2_api_ablation/${candidate}/long_run" \
  --config "${cfg}" \
  --image_concurrency 1 \
  --no-resume \
  --force_api

python -m finix_restore.cli \
  --input_dir outputs/chunk_eval/s2_api_ablation/samples/table/images \
  --output_csv "outputs/chunk_eval/s2_api_ablation/${candidate}/table_submission.csv" \
  --work_dir "outputs/chunk_eval/s2_api_ablation/${candidate}/table_run" \
  --config "${cfg}" \
  --image_concurrency 1 \
  --no-resume \
  --force_api
```

Replace `candidate="baseline_5m"` with each line from `candidates.txt`.

Expected:

- Each long run writes `long_submission.csv`.
- Each table run writes `table_submission.csv`.
- If a run fails due to API timeout or quality gate, keep the logs and record the failure in `outputs/chunk_eval/s2_api_ablation/<candidate>/run_notes.md`.

- [ ] **Step 2: Validate S2 submissions**

For each candidate:

```bash
python -m scripts.chunk_eval.validate_submission \
  --csv "outputs/chunk_eval/s2_api_ablation/${candidate}/long_submission.csv" \
  --expected_count 10 \
  --out "outputs/chunk_eval/s2_api_ablation/${candidate}/long_validation.json"

python -m scripts.chunk_eval.validate_submission \
  --csv "outputs/chunk_eval/s2_api_ablation/${candidate}/table_submission.csv" \
  --expected_count 10 \
  --out "outputs/chunk_eval/s2_api_ablation/${candidate}/table_validation.json"
```

Expected: exit 0 for valid CSVs. If empty outputs exist, they are recorded in JSON; empty outputs do not by themselves fail validation.

- [ ] **Step 3: Score S2 predictions**

For each candidate:

```bash
python -m finix_restore.eval.cli \
  --pred "outputs/chunk_eval/s2_api_ablation/${candidate}/long_submission.csv" \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --output "outputs/chunk_eval/s2_api_ablation/${candidate}/long_metrics.json"

python -m finix_restore.eval.cli \
  --pred "outputs/chunk_eval/s2_api_ablation/${candidate}/table_submission.csv" \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --output "outputs/chunk_eval/s2_api_ablation/${candidate}/table_metrics.json"
```

Expected: CLI prints file count, table sample count, mean Text Edit, Table TEDS, Read Order Edit, and Overall.

- [ ] **Step 4: Summarize S2 metrics**

For each candidate:

```bash
python -m scripts.chunk_eval.summarize_metrics \
  --metric long "outputs/chunk_eval/s2_api_ablation/${candidate}/long_metrics.json" \
  --metric table "outputs/chunk_eval/s2_api_ablation/${candidate}/table_metrics.json" \
  --out "outputs/chunk_eval/s2_api_ablation/${candidate}/metrics_summary.md" \
  --top_n 10
```

Expected: writes `metrics_summary.md`.

- [ ] **Step 5: Select S3 candidate**

Compare candidates using:

- Higher `mean_overall`.
- Lower `fail_requests` in `logs/run.jsonl`.
- Lower empty output count in validation JSON.
- Better table score without unacceptable long regression.

Write the selected candidate name to:

```text
outputs/chunk_eval/s3_train_eval/selected_candidate.txt
```

The file must contain exactly one config name, for example:

```text
table_4m_safe
```

## 13. Task 12: Execute S3 Training Evaluation

**Files:** run artifacts under `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/s3_train_eval/`

This task calls FinixDoc-VL and may take substantial time. Run long and table separately so each prediction CSV maps to one GT directory.

- [ ] **Step 1: Copy selected config snapshot**

Run:

```bash
candidate="$(cat outputs/chunk_eval/s3_train_eval/selected_candidate.txt)"
mkdir -p outputs/chunk_eval/s3_train_eval
cp "scripts/chunk_eval/configs/${candidate}.yaml" outputs/chunk_eval/s3_train_eval/selected_config.yaml
```

Expected: `outputs/chunk_eval/s3_train_eval/selected_config.yaml` exists.

- [ ] **Step 2: Run long training prediction**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/images" \
  --output_csv outputs/chunk_eval/s3_train_eval/long_submission.csv \
  --work_dir outputs/chunk_eval/s3_train_eval/long_run \
  --config outputs/chunk_eval/s3_train_eval/selected_config.yaml \
  --image_concurrency 1
```

Expected: writes `long_submission.csv`. If interrupted by API instability, keep partial run artifacts and resume with the same command because `resume` defaults to true.

- [ ] **Step 3: Run table training prediction**

Run:

```bash
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --output_csv outputs/chunk_eval/s3_train_eval/table_submission.csv \
  --work_dir outputs/chunk_eval/s3_train_eval/table_run \
  --config outputs/chunk_eval/s3_train_eval/selected_config.yaml \
  --image_concurrency 1
```

Expected: writes `table_submission.csv`. If API instability prevents full completion, record completed count and failure reason in `outputs/chunk_eval/s3_train_eval/run_notes.md`.

- [ ] **Step 4: Validate S3 CSVs**

Run:

```bash
python -m scripts.chunk_eval.validate_submission \
  --csv outputs/chunk_eval/s3_train_eval/long_submission.csv \
  --expected_count 100 \
  --out outputs/chunk_eval/s3_train_eval/long_validation.json

python -m scripts.chunk_eval.validate_submission \
  --csv outputs/chunk_eval/s3_train_eval/table_submission.csv \
  --expected_count 100 \
  --out outputs/chunk_eval/s3_train_eval/table_validation.json
```

Expected: both validators exit 0. If not, inspect JSON risks before scoring.

- [ ] **Step 5: Score S3 CSVs**

Run:

```bash
python -m finix_restore.eval.cli \
  --pred outputs/chunk_eval/s3_train_eval/long_submission.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --output outputs/chunk_eval/s3_train_eval/long_metrics.json

python -m finix_restore.eval.cli \
  --pred outputs/chunk_eval/s3_train_eval/table_submission.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --output outputs/chunk_eval/s3_train_eval/table_metrics.json
```

Expected: each command prints summary metrics and writes JSON.

- [ ] **Step 6: Summarize S3 metrics**

Run:

```bash
python -m scripts.chunk_eval.summarize_metrics \
  --metric long outputs/chunk_eval/s3_train_eval/long_metrics.json \
  --metric table outputs/chunk_eval/s3_train_eval/table_metrics.json \
  --out outputs/chunk_eval/s3_train_eval/metrics_summary.md \
  --top_n 10
```

Expected: writes `outputs/chunk_eval/s3_train_eval/metrics_summary.md`.

## 14. Task 13: Diagnose Failures And Write Final Report

**Files:**

- Modify: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`
- Run artifact: `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/outputs/chunk_eval/final_report.md`

- [ ] **Step 1: Inspect validation and worst-file evidence**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
for path in [
    "outputs/chunk_eval/s3_train_eval/long_validation.json",
    "outputs/chunk_eval/s3_train_eval/table_validation.json",
]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    print(path, data)
PY
```

Expected: prints validation summaries without secrets.

- [ ] **Step 2: Inspect API failure counts**

Run:

```bash
python scripts/chunk_budget_experiment/aggregate_api_elapsed.py \
  --root outputs/chunk_eval/s3_train_eval \
  --out outputs/chunk_eval/s3_train_eval/api_elapsed_summary.csv
```

Expected: writes `api_elapsed_summary.csv`. If it prints `wrote 0 rows`, note that the aggregator expects budget-style nesting and inspect `long_run/logs/run.jsonl` and `table_run/logs/run.jsonl` manually.

- [ ] **Step 3: Write final report**

Run:

```bash
python -m scripts.chunk_eval.write_final_report \
  --out outputs/chunk_eval/final_report.md \
  --dry_run_md outputs/chunk_eval/s1_dry_run/summary.csv \
  --s2_md outputs/chunk_eval/s2_api_ablation/baseline_5m/metrics_summary.md \
  --s3_md outputs/chunk_eval/s3_train_eval/metrics_summary.md \
  --finding "API 失败、空输出和超时按 validation JSON 与 logs/run.jsonl 量化。" \
  --finding "Read Order 失分按标题层级、段落切分和接缝重复三类人工抽查最差样本。" \
  --finding "Table TEDS 失分按密集数字 OCR、表格行列结构和 HTML 合法性三类定位。" \
  --next_step "P0：若失败切片比例高，先降低 API 并发并延长退避，避免空输出污染评分。" \
  --next_step "P1：若 table_4m_safe 优于 baseline_5m，将 table target 固化到默认候选并继续做行级切分。" \
  --next_step "P1：若 Read Order 是 long 主损失，优先做编号标题层级归一化和段落边界规则。" \
  --next_step "P2：保留 large_8m_probe 作为后续极小样本验证，不进入默认全量策略。"
```

Expected: writes `outputs/chunk_eval/final_report.md`.

- [ ] **Step 4: Append experiment index entry**

Append this section to `/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/experiments.md`:

```markdown

## 2026-06-23 训练集切图实验与测评分析

- 设计文档：`docs/superpowers/specs/2026-06-23-chunking-evaluation-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-23-chunking-evaluation-execution.md`
- 运行产物：`outputs/chunk_eval/`
- 最终报告：`outputs/chunk_eval/final_report.md`

结论以最终报告为准；`outputs/` 只作为本地运行产物，不提交。
```

- [ ] **Step 5: Commit docs index update**

Run:

```bash
git add docs/experiments.md
git commit -m "docs(exp): index chunking evaluation run"
```

## 15. Task 14: Final Verification

**Files:** no planned source changes.

- [ ] **Step 1: Run core tests**

Run:

```bash
pytest tests/test_chunk_eval_profile.py \
  tests/test_chunk_eval_prepare_samples.py \
  tests/test_chunk_eval_validate_submission.py \
  tests/test_chunk_eval_summarize_metrics.py \
  tests/test_eval_scorer.py \
  tests/test_submission.py -q
```

Expected: all pass.

- [ ] **Step 2: Check git diff whitespace**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 3: Check worktree**

Run:

```bash
git status --short
```

Expected:

- Source/test/docs changes are committed.
- `outputs/` may appear only if it is not gitignored; do not add it.

- [ ] **Step 4: Final response evidence**

Report:

- Path to final report.
- Selected chunking config.
- Long/table Overall and component metrics.
- Whether full 100+100 train evaluation completed.
- Any API failures or empty outputs.
- Tests run and pass/fail status.

## 16. Self-review Checklist

Spec coverage:

- S0 profile: Task 8.
- S1 dry-run matrix: Task 9.
- S2 deterministic sample and API ablation: Tasks 10-11.
- S3 long/table separated train evaluation and scoring: Task 12.
- CSV validation: Tasks 4, 11, 12.
- Failure diagnosis and final Markdown report: Task 13.
- Constraints on `data/`, `.env`, outputs, and FinixDoc-VL-only usage: Sections 0, 11, 12.

Type consistency:

- Profile output uses `subset,file_name,width,height,pixels,aspect,doc_type,risk_level,pixel_bucket`.
- Sample manifest preserves profile fields and adds `selected_reason`.
- Validation reports use `passed,rows,expected_count,duplicate_file_names,empty_file_names,empty_outputs,risks`.
- Metric summary consumes existing `finix_restore.eval.cli` JSON keys.

Execution risks:

- API instability may prevent S3 full completion; Task 12 requires recording run notes and allows resume.
- `aggregate_api_elapsed.py` expects budget-style nesting; Task 13 explicitly handles the zero-row case.
- Empty `ground_truth` outputs are recorded as risk evidence, not silently ignored.
