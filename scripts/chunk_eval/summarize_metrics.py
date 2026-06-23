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
