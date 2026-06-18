# Dataset Statistics Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate `docs/赛题数据统计分析.md` with image-size and file-size distribution analysis for both A榜评测数据集 and training data.

**Architecture:** Use a temporary local Python script under `outputs/` to read image metadata with Pillow, summarize distributions with pandas, and render a Markdown report. The script is a run artifact and is not part of the committed project surface; the committed deliverable is the report document.

**Tech Stack:** Python 3, Pillow, pandas, pathlib, standard library `math`, `statistics`, and `os`.

---

## File Structure

- Modify: `docs/赛题数据统计分析.md`
  - Final human-readable report with summary tables and engineering recommendations.
- Create temporarily: `outputs/tmp_dataset_stats.py`
  - Local one-off script to collect metadata, compute grouped statistics, and render Markdown.
- Create temporarily: `outputs/tmp_dataset_stats.csv`
  - Local one-off row-level metadata table used for validation and spot checks.

Do not modify files under `data/`. Do not read `.env`. Do not call FinixDoc-VL or any external model/API.

## Task 1: Collect Image Metadata

**Files:**
- Create: `outputs/tmp_dataset_stats.py`
- Create: `outputs/tmp_dataset_stats.csv`

- [ ] **Step 1: Write the metadata collection script**

Create `outputs/tmp_dataset_stats.py` with this content:

```python
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from PIL import Image

ROOT = Path("/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2")
DATASETS = [
    ("A榜", "long", ROOT / "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images"),
    ("A榜", "table", ROOT / "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images"),
    ("训练集", "long", ROOT / "data/AFAC 训练数据集/finixdocbench_huge_long_100/images"),
    ("训练集", "table", ROOT / "data/AFAC 训练数据集/finixdocbench_huge_table_100/images"),
]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
MAX_MODEL_PIXELS = 16_777_216
TARGET_CHUNK_PIXELS = 4_000_000


def collect_rows() -> list[dict[str, object]]:
    Image.MAX_IMAGE_PIXELS = None
    rows: list[dict[str, object]] = []
    for split, subset, image_dir in DATASETS:
        for path in sorted(image_dir.iterdir()):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            with Image.open(path) as img:
                width, height = img.size
                image_format = img.format or path.suffix.lower().lstrip(".").upper()
            pixels = width * height
            short_side = max(1, min(width, height))
            aspect = max(width, height) / short_side
            size_bytes = path.stat().st_size
            rows.append(
                {
                    "split": split,
                    "subset": subset,
                    "file_name": path.name,
                    "path": str(path),
                    "format": image_format,
                    "width": width,
                    "height": height,
                    "pixels": pixels,
                    "megapixels": pixels / 1_000_000,
                    "file_size_mb": size_bytes / 1_048_576,
                    "aspect": aspect,
                    "over_16m": pixels > MAX_MODEL_PIXELS,
                    "over_50m": pixels > 50_000_000,
                    "over_100m": pixels > 100_000_000,
                    "over_200m": pixels > 200_000_000,
                    "estimated_min_chunks_4m": math.ceil(pixels / TARGET_CHUNK_PIXELS),
                    "estimated_min_chunks_16m": math.ceil(pixels / MAX_MODEL_PIXELS),
                }
            )
    return rows


def main() -> None:
    out_csv = ROOT / "outputs/tmp_dataset_stats.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(collect_rows())
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"rows={len(df)}")
    print(df.groupby(["split", "subset"]).size())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

Run:

```bash
python outputs/tmp_dataset_stats.py
```

Expected output includes exactly these group counts:

```text
rows=300
split  subset
A榜     long       50
       table      50
训练集    long      100
       table     100
```

- [ ] **Step 3: Validate the CSV row count**

Run:

```bash
python - <<'PY'
import pandas as pd
df = pd.read_csv("outputs/tmp_dataset_stats.csv")
assert len(df) == 300, len(df)
assert set(df["split"]) == {"A榜", "训练集"}
assert set(df["subset"]) == {"long", "table"}
assert df["file_name"].notna().all()
print("metadata csv ok")
PY
```

Expected output:

```text
metadata csv ok
```

## Task 2: Generate Markdown Report

**Files:**
- Modify: `outputs/tmp_dataset_stats.py`
- Modify: `docs/赛题数据统计分析.md`

- [ ] **Step 1: Extend the script with Markdown rendering**

Append these functions before `main()` in `outputs/tmp_dataset_stats.py`:

```python
def fmt_num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return ""
    return f"{value:,.{digits}f}"


def fmt_int(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{int(round(value)):,}"


def summarize_group(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["split", "subset"], sort=False)
    rows = []
    for (split, subset), part in grouped:
        rows.append(
            {
                "数据集": split,
                "子集": subset,
                "张数": len(part),
                "像素中位数(M)": part["megapixels"].median(),
                "像素P90(M)": part["megapixels"].quantile(0.90),
                "像素最大(M)": part["megapixels"].max(),
                "长宽比中位数": part["aspect"].median(),
                "长宽比最大": part["aspect"].max(),
                "文件大小中位数(MB)": part["file_size_mb"].median(),
                ">16M张数": int(part["over_16m"].sum()),
                ">100M张数": int(part["over_100m"].sum()),
                "4M切片估算总数": int(part["estimated_min_chunks_4m"].sum()),
            }
        )
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame, int_cols: set[str] | None = None) -> str:
    int_cols = int_cols or set()
    lines = []
    headers = list(df.columns)
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for _, row in df.iterrows():
        cells = []
        for col in headers:
            value = row[col]
            if isinstance(value, float):
                cells.append(fmt_int(value) if col in int_cols else fmt_num(value))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def top_extremes(df: pd.DataFrame, metric: str, n: int = 5) -> pd.DataFrame:
    cols = ["split", "subset", "file_name", "width", "height", "megapixels", "file_size_mb", "aspect", "estimated_min_chunks_4m"]
    return df.sort_values(metric, ascending=False).head(n)[cols].rename(
        columns={
            "split": "数据集",
            "subset": "子集",
            "file_name": "文件名",
            "width": "宽",
            "height": "高",
            "megapixels": "像素(M)",
            "file_size_mb": "大小(MB)",
            "aspect": "长宽比",
            "estimated_min_chunks_4m": "4M切片数",
        }
    )


def render_report(df: pd.DataFrame) -> str:
    summary = summarize_group(df)
    total_chunks_4m = int(df["estimated_min_chunks_4m"].sum())
    total_chunks_16m = int(df["estimated_min_chunks_16m"].sum())
    over_16m = int(df["over_16m"].sum())
    over_100m = int(df["over_100m"].sum())
    max_pixels = df.loc[df["megapixels"].idxmax()]
    max_aspect = df.loc[df["aspect"].idxmax()]
    lines = [
        "# 赛题数据统计分析",
        "",
        "## 1. 可执行结论",
        "",
        f"- 本次纳入训练集与 A 榜共 {len(df)} 张图片，其中 long 类 {int((df['subset'] == 'long').sum())} 张，table 类 {int((df['subset'] == 'table').sum())} 张。",
        f"- 超过 FinixDoc-VL 约 16M 单图像素预算的图片有 {over_16m} 张，超过 100M 像素的极端图片有 {over_100m} 张，整图直传不是可行默认策略。",
        f"- 按当前 `configs/default.yaml` 中 `chunk.max_chunk_pixels=4M` 粗估，300 张图至少需要 {total_chunks_4m:,} 个切片；如果按 16M 硬预算粗估，也至少需要 {total_chunks_16m:,} 个切片。",
        f"- 最大像素样本为 `{max_pixels['file_name']}`，约 {max_pixels['megapixels']:.2f}M 像素；最大长宽比样本为 `{max_aspect['file_name']}`，长宽比约 {max_aspect['aspect']:.2f}。",
        "- 策略上应把 long 和 table 分开调参：long 优先保证纵向覆盖、接缝去重和标题连续性；table 优先控制二维切块、表头重复和 HTML 表格合法性。",
        "",
        "## 2. 数据范围与统计口径",
        "",
        "- A榜 long：`data/AFAC A榜评测数据集/finix_huge_long_rest_A/images`",
        "- A榜 table：`data/AFAC A榜评测数据集/finix_huge_table_rest_A/images`",
        "- 训练集 long：`data/AFAC 训练数据集/finixdocbench_huge_long_100/images`",
        "- 训练集 table：`data/AFAC 训练数据集/finixdocbench_huge_table_100/images`",
        "",
        "统计仅读取图片尺寸和文件大小，不修改原始数据，不调用 API。像素上限参照 `docs/FinixDoc-VL的图片尺寸说明.md` 中约 16.78M 的单次输入预算；切片估算参照当前默认配置 `chunk.max_chunk_pixels=4,000,000`。",
        "",
        "## 3. 总体规模概览",
        "",
        markdown_table(summary, int_cols={"张数", ">16M张数", ">100M张数", "4M切片估算总数"}),
        "",
        "## 4. 训练集与 A榜分布对比",
        "",
        "A榜每类 50 张，训练集每类 100 张，目录结构和类别划分一致，适合用训练集先调参再迁移到 A榜。需要注意的是，迁移不能依赖文件名，只能依赖尺寸、长宽比、投影密度、表格线密度等可解释特征。",
        "",
        "从统计指标看，重点比较三类差异：像素 P90 决定常规切块压力，最大值决定兜底策略，长宽比分布决定是纵向滑窗还是二维网格优先。若 A榜某类最大值显著高于训练集，应优先为该类保守降低并发、增加超时和重试预算。",
        "",
        "## 5. 长条类图片分析",
        "",
        "long 类图片的主要风险是高度远大于宽度，单图内容跨越大量页面片段。切块策略应保持原图宽度，沿纵向滑窗切分，并在 200-400px overlap 上做接缝去重。长宽比越高，越容易出现章节标题跨块、页眉页脚重复和段落截断。",
        "",
        "## 6. 表格类图片分析",
        "",
        "table 类图片的主要风险是单页像素高、二维信息密集。对低于整页阈值的样本可以尝试整页作为全局参考；对高像素样本应优先二维网格切块。横向 overlap 应保护跨列表头，纵向 overlap 应保护跨行单元格，后处理需重点检查重复表头、空单元格和 HTML 标签闭合。",
        "",
        "## 7. FinixDoc-VL 输入约束与切片压力",
        "",
        f"- `>16M` 图片数：{over_16m}",
        f"- `>50M` 图片数：{int(df['over_50m'].sum())}",
        f"- `>100M` 图片数：{over_100m}",
        f"- `>200M` 图片数：{int(df['over_200m'].sum())}",
        f"- 4M 目标切片估算总数：{total_chunks_4m:,}",
        f"- 16M 硬预算切片估算总数：{total_chunks_16m:,}",
        "",
        "这些数字是理论下限，真实请求数会因为 overlap、空白切线、失败重试、表格补切而更高。因此 API 调度应按请求量峰值而不是图片张数估算耗时。",
        "",
        "## 8. 极端样本诊断",
        "",
        "### 像素最大样本",
        "",
        markdown_table(top_extremes(df, "megapixels"), int_cols={"宽", "高", "4M切片数"}),
        "",
        "### 文件大小最大样本",
        "",
        markdown_table(top_extremes(df, "file_size_mb"), int_cols={"宽", "高", "4M切片数"}),
        "",
        "### 长宽比最大样本",
        "",
        markdown_table(top_extremes(df, "aspect"), int_cols={"宽", "高", "4M切片数"}),
        "",
        "这些样本只用于理解压力来源，不应写入任何按测试文件名分支的特判逻辑。",
        "",
        "## 9. 对方案优化的建议",
        "",
        "1. `ImageProfiler` 应保留像素、长宽比、文件大小、估算切片数，并把 `>16M` 和 `>100M` 作为风险标签写入 profile。",
        "2. long 类默认使用纵向滑窗，优先把窗口控制在 1M-4M 像素工作点；极端长图按高度自适应增加切片数，不应为了减少请求而把切片推到 16M 附近。",
        "3. table 类需要先按像素判断是否整页解析；超过整页阈值时采用二维切块，并保留 row/col/bbox 以支持后续阅读顺序和表格合并。",
        "4. API 并发不宜只按图片数估算。应按 `estimated_min_chunks_4m` 加上 overlap 和重试倍率估算请求总量，再决定并发、超时和 userId 轮询。",
        "5. 质量门禁应优先覆盖空输出、异常短输出、重复率、HTML 表格不闭合和切块覆盖缺口，这些问题与本数据集的高像素和高长宽比分布直接相关。",
        "",
    ]
    return "\n".join(lines)
```

Replace `main()` with:

```python
def main() -> None:
    out_csv = ROOT / "outputs/tmp_dataset_stats.csv"
    out_report = ROOT / "docs/赛题数据统计分析.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(collect_rows())
    df.to_csv(out_csv, index=False, encoding="utf-8")
    out_report.write_text(render_report(df), encoding="utf-8")
    print(f"rows={len(df)}")
    print(df.groupby(["split", "subset"]).size())
    print(f"wrote={out_report}")
```

- [ ] **Step 2: Run the report generator**

Run:

```bash
python outputs/tmp_dataset_stats.py
```

Expected output includes:

```text
rows=300
wrote=/Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/赛题数据统计分析.md
```

- [ ] **Step 3: Inspect the generated report**

Run:

```bash
sed -n '1,260p' docs/赛题数据统计分析.md
```

Expected: report contains the nine sections listed in the design spec, concrete numeric values, and Markdown tables.

## Task 3: Validate Report and Repository Safety

**Files:**
- Modify: `docs/赛题数据统计分析.md`

- [ ] **Step 1: Verify sample counts from filesystem**

Run:

```bash
find 'data/AFAC A榜评测数据集' -path '*/images/*' -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l
find 'data/AFAC 训练数据集' -path '*/images/*' -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l
```

Expected output:

```text
100
200
```

- [ ] **Step 2: Verify report has no sensitive values**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path("docs/赛题数据统计分析.md").read_text(encoding="utf-8")
for forbidden in ["FINIX_API_KEY=", "apiKey=", "sk-", "Bearer "]:
    assert forbidden not in text, forbidden
print("secret scan ok")
PY
```

Expected output:

```text
secret scan ok
```

- [ ] **Step 3: Verify `data/` was not modified**

Run:

```bash
git status --short data
```

Expected: no output.

- [ ] **Step 4: Review final diff**

Run:

```bash
git diff -- docs/赛题数据统计分析.md
```

Expected: only the generated report content changes.

- [ ] **Step 5: Run markdown-sensitive whitespace check**

Run:

```bash
git diff --check -- docs/赛题数据统计分析.md
```

Expected: no output.

## Task 4: Commit Deliverable

**Files:**
- Modify: `docs/赛题数据统计分析.md`

- [ ] **Step 1: Stage only the final report**

Run:

```bash
git add docs/赛题数据统计分析.md
```

- [ ] **Step 2: Commit**

Run:

```bash
git commit -m "docs: add dataset statistics analysis"
```

Expected: commit succeeds and includes only `docs/赛题数据统计分析.md`.

- [ ] **Step 3: Leave temporary outputs untracked**

Run:

```bash
git status --short outputs/tmp_dataset_stats.py outputs/tmp_dataset_stats.csv
```

Expected: files may appear as untracked run artifacts; do not commit them.
