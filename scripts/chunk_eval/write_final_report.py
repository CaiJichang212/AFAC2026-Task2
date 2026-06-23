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
