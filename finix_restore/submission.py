from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from finix_restore.models import QualityReport


class SubmissionWriter:
    columns = ["file_name", "ground_truth"]

    def write(
        self,
        rows: Sequence[dict[str, str]],
        output_csv: Path,
        expected_file_names: Sequence[str] | None = None,
    ) -> QualityReport:
        output_csv = Path(output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows, columns=self.columns)
        df.to_csv(output_csv, index=False, encoding="utf-8", lineterminator="\n")
        return self._validate(output_csv, expected_file_names or [row["file_name"] for row in rows])

    def _validate(self, output_csv: Path, expected_file_names: Sequence[str]) -> QualityReport:
        risks: list[str] = []
        try:
            df = pd.read_csv(output_csv)
        except Exception as exc:  # pragma: no cover - pandas parser exceptions vary
            return QualityReport(False, ["csv_unreadable"], {"error": str(exc)})
        if list(df.columns) != self.columns:
            risks.append("csv_columns")
        if len(df) != len(expected_file_names):
            risks.append("csv_row_count")
        if "file_name" in df.columns:
            if df["file_name"].duplicated().any():
                risks.append("csv_duplicate_file_name")
            if set(df["file_name"].astype(str)) != set(expected_file_names):
                risks.append("csv_file_name_mismatch")
        return QualityReport(
            passed=not risks,
            risks=risks,
            metrics={"row_count": len(df), "expected_row_count": len(expected_file_names)},
        )
