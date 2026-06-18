from __future__ import annotations

from finix_restore.models import QualityReport


class RetryPlanner:
    def __init__(self, max_reruns_per_file: int = 2) -> None:
        self.max_reruns_per_file = max_reruns_per_file

    def plan(self, report: QualityReport, rerun_count: int = 0) -> dict[str, bool | float | int | list[str]]:
        actions: dict[str, bool | float | int | list[str]] = {
            "rerun": False,
            "window_scale": 1.0,
            "overlap_scale": 1.0,
            "table_grid_scale": 1.0,
            "concurrency": 0,
            "reasons": list(report.risks),
        }
        if report.passed or rerun_count >= self.max_reruns_per_file:
            return actions

        risks = set(report.risks)
        if "empty_output" in risks:
            actions["window_scale"] = 0.7
            actions["concurrency"] = 1
        if "too_short" in risks:
            actions["overlap_scale"] = 1.5
        if "html_broken" in risks:
            actions["table_grid_scale"] = 0.7
        if "api_timeout" in risks or "api_failure_ratio_high" in risks:
            actions["window_scale"] = min(float(actions["window_scale"]), 0.7)
            actions["concurrency"] = 1

        actions["rerun"] = True
        return actions
