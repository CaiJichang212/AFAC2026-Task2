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
        # 仅"限流/繁忙/HTML 破碎/整体失败率过高"这类真正与服务端并发压力相关的
        # 风险才应把重跑并发降为 1; 其它风险 (too_short, table_reference_missing
        # 等) 与并发无关, 强行串行只会成倍拖慢重跑。
        throttling_risks = {
            "service_busy_html",
            "full_html_page",
            "html_broken",
            "api_failure_ratio_high",
        }
        if "empty_output" in risks or "force_retry_empty" in risks:
            actions["force_api"] = True
            # empty_output 未必是限流引起, 不再强制降到 1; 若同时有限流风险后面会覆盖。
        if throttling_risks & risks:
            actions["force_api"] = True
            actions["concurrency"] = 1
        table_layout_risks = {
            "table_count_explosion",
            "table_assembly_uncertain",
            "table_reference_missing",
            "horizontal_split_unmerged",
        }
        if table_layout_risks & risks:
            actions["force_rowband"] = True
        if {"table_count_explosion", "horizontal_split_unmerged"} & risks:
            actions["disable_horizontal_split"] = True
        if "too_short" in risks:
            actions["overlap_scale"] = 1.5
            if report.metrics.get("doc_type") == "table_page":
                actions["table_grid_scale"] = 1.15

        actions["rerun"] = True
        return actions
