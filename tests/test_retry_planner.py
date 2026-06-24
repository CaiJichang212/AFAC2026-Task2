from finix_restore.models import QualityReport
from finix_restore.retry_planner import RetryPlanner


def test_retry_planner_maps_table_v2_risks_to_rowband_actions():
    planner = RetryPlanner(max_reruns_per_file=2)
    report = QualityReport(
        passed=False,
        risks=["table_count_explosion", "horizontal_split_unmerged"],
        metrics={"doc_type": "table_page"},
    )

    plan = planner.plan(report, rerun_count=0)

    assert plan["rerun"] is True
    assert plan["force_api"] is False
    assert plan["concurrency"] == 1
    assert plan["force_rowband"] is True
    assert plan["disable_horizontal_split"] is True


def test_retry_planner_for_html_broken_keeps_force_api():
    planner = RetryPlanner(max_reruns_per_file=2)
    report = QualityReport(
        passed=False,
        risks=["html_broken", "table_assembly_uncertain", "table_reference_missing"],
        metrics={"doc_type": "table_page"},
    )

    plan = planner.plan(report, rerun_count=0)

    assert plan["rerun"] is True
    assert plan["force_api"] is True
    assert plan["concurrency"] == 1
    assert plan["force_rowband"] is True
    assert plan["disable_horizontal_split"] is False
