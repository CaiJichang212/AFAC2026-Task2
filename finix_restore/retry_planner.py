from __future__ import annotations

from finix_restore.models import QualityReport


class RetryPlanner:
    def __init__(self, max_reruns_per_file: int = 2) -> None:
        self.max_reruns_per_file = max_reruns_per_file

    def plan(self, report: QualityReport, rerun_count: int = 0) -> dict[str, bool | float | int | list[str]]:
        actions: dict[str, bool | float | int | list[str]] = {
            "rerun": False,
            "force_api": False,
            "force_rowband": False,
            "disable_horizontal_split": False,
            "window_scale": 1.0,
            "overlap_scale": 1.0,
            "table_grid_scale": 1.0,
            "concurrency": 0,
            "reasons": list(report.risks),
        }
        if report.passed or rerun_count >= self.max_reruns_per_file:
            return actions

        risks = set(report.risks)
        if "service_busy_html" in risks or "full_html_page" in risks:
            actions["force_api"] = True
            actions["concurrency"] = 1
        if "html_broken" in risks:
            actions["force_api"] = True
            actions["concurrency"] = 1
        if "api_failure_ratio_high" in risks:
            actions["concurrency"] = 1
        if {"table_count_explosion", "table_assembly_uncertain", "table_reference_missing", "horizontal_split_unmerged"} & risks:
            actions["force_rowband"] = True
            actions["concurrency"] = max(1, int(actions["concurrency"]))
        if {"table_count_explosion", "horizontal_split_unmerged"} & risks:
            actions["disable_horizontal_split"] = True
            actions["concurrency"] = max(1, int(actions["concurrency"]))
        if "too_short" in risks:
            actions["overlap_scale"] = 1.5
            if report.metrics.get("doc_type") == "table_page":
                actions["table_grid_scale"] = 1.15
                actions["concurrency"] = max(1, int(actions["concurrency"]))

        actions["rerun"] = True
        return actions
