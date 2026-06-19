from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Sequence

import pandas as pd

from finix_restore.models import DocType, ProcessedFile, QualityReport
from finix_restore.paths import RunPaths


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SERVICE_BUSY_HTML_MARKERS = (
    "服务器繁忙",
    "顾客太多",
    "j_retry_link",
    "showtextwait",
    "支付宝版权所有",
)


class QualityGate:
    def __init__(
        self,
        paths: RunPaths,
        max_duplication_ratio: float = 0.18,
        max_api_failure_ratio: float = 0.20,
        min_chars_by_type: dict[str, int] | None = None,
    ) -> None:
        self.paths = paths
        self.max_duplication_ratio = max_duplication_ratio
        self.max_api_failure_ratio = max_api_failure_ratio
        self.min_chars_by_type = min_chars_by_type or {
            "long_strip": 2000,
            "table_page": 5000,
        }

    def validate_input_files(self, input_dirs: Sequence[Path]) -> QualityReport:
        names: list[str] = []
        for input_dir in input_dirs:
            for path in sorted(Path(input_dir).iterdir()):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    names.append(path.name)
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        risks = ["duplicate_input_file_name"] if duplicates else []
        return QualityReport(
            passed=not risks,
            risks=risks,
            metrics={"image_count": len(names), "duplicate_count": len(duplicates)},
        )

    def check_submission(self, output_csv: Path, expected_file_names: Sequence[str]) -> QualityReport:
        risks: list[str] = []
        metrics: dict[str, float | int | str] = {}
        try:
            df = pd.read_csv(output_csv)
        except Exception as exc:  # pragma: no cover - pandas exception types vary by parser path
            return QualityReport(False, ["csv_unreadable"], {"error": str(exc)})

        expected_columns = ["file_name", "ground_truth"]
        if list(df.columns) != expected_columns:
            risks.append("csv_columns")
        metrics["row_count"] = len(df)
        metrics["expected_row_count"] = len(expected_file_names)
        if len(df) != len(expected_file_names):
            risks.append("csv_row_count")

        if "file_name" in df.columns:
            if df["file_name"].duplicated().any():
                risks.append("csv_duplicate_file_name")
            actual = set(df["file_name"].astype(str))
            expected = set(expected_file_names)
            if actual != expected:
                risks.append("csv_file_name_mismatch")

        return QualityReport(passed=not risks, risks=risks, metrics=metrics)

    def check_file(
        self,
        file_name: str,
        markdown: str,
        doc_type: DocType,
        chunk_count: int,
        failed_chunks: int,
        extra_metrics: dict[str, float | int | str] | None = None,
    ) -> QualityReport:
        risks: list[str] = []
        text = markdown or ""
        stripped = text.strip()
        if not stripped:
            risks.append("empty_output")
        elif len(stripped) < self.min_chars_by_type.get(doc_type, 0):
            risks.append("too_short")

        duplication_ratio = self._duplication_ratio(text)
        if duplication_ratio > self.max_duplication_ratio:
            risks.append("high_duplication")

        risks.extend(self.detect_forbidden_html(text))
        if self._html_is_broken(text):
            risks.append("html_broken")

        failure_ratio = failed_chunks / chunk_count if chunk_count else 0.0
        if failure_ratio > self.max_api_failure_ratio:
            risks.append("api_failure_ratio_high")

        metrics = {
            "chars": len(stripped),
            "duplication_ratio": duplication_ratio,
            "chunk_count": chunk_count,
            "failed_chunks": failed_chunks,
            "api_failure_ratio": failure_ratio,
            "doc_type": doc_type,
        }
        if extra_metrics:
            metrics.update(extra_metrics)
        report = QualityReport(
            passed=not risks,
            risks=list(dict.fromkeys(risks)),
            metrics=metrics,
        )
        self._write_file_report(file_name, report)
        return report

    def write_run_summary(
        self,
        processed_files: Sequence[ProcessedFile],
        output_csv: Path | None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        risk_counts = Counter()
        failed_files: list[str] = []
        files_payload: list[dict[str, object]] = []
        for processed in processed_files:
            if not processed.quality.passed:
                failed_files.append(processed.file_name)
            for risk in processed.quality.risks:
                risk_counts[risk] += 1
            files_payload.append(
                {
                    "file_name": processed.file_name,
                    "rerun_count": processed.rerun_count,
                    "quality": {
                        "passed": processed.quality.passed,
                        "risks": processed.quality.risks,
                        "metrics": processed.quality.metrics,
                    },
                }
            )

        summary = {
            "passed": not failed_files,
            "failed_files": failed_files,
            "risk_counts": dict(risk_counts),
            "file_count": len(processed_files),
            "output_csv": str(output_csv) if output_csv is not None else None,
            "dry_run": dry_run,
            "files": files_payload,
        }
        self.paths.qc_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.qc_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    def detect_forbidden_html(self, markdown: str) -> list[str]:
        lowered = markdown.strip().lower()
        if not lowered:
            return []
        risks: list[str] = []
        is_full_html = (
            (lowered.startswith("<!doctype html") or lowered.startswith("<html"))
            and "<head" in lowered
            and "<body" in lowered
        )
        if is_full_html:
            risks.append("full_html_page")
            if any(marker in lowered for marker in SERVICE_BUSY_HTML_MARKERS) or (
                "alipayobjects.com" in lowered and "<html" in lowered
            ):
                risks.append("service_busy_html")
        return risks

    def _write_file_report(self, file_name: str, report: QualityReport) -> None:
        stem = Path(file_name).stem
        self.paths.qc_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.qc_dir / f"{stem}.json").write_text(
            json.dumps(
                {
                    "passed": report.passed,
                    "risks": report.risks,
                    "metrics": report.metrics,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _duplication_ratio(self, markdown: str) -> float:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        if not lines:
            return 0.0
        seen: set[str] = set()
        duplicate_chars = 0
        total_chars = sum(len(line) for line in lines)
        for line in lines:
            if line in seen:
                duplicate_chars += len(line)
            else:
                seen.add(line)
        if total_chars == 0:
            return 0.0
        return duplicate_chars / total_chars

    def _html_is_broken(self, markdown: str) -> bool:
        lowered = markdown.lower()
        for tag in ("table", "tr", "td", "th"):
            opens = lowered.count(f"<{tag}") - lowered.count(f"</{tag}")
            if opens > 0:
                return True
        return False
