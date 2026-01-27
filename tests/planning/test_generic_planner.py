from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import DiagnosticStage, Identity, ValidationRowResult, ValidationErrorItem
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.planning.generic_planner import GenericPlanner
from connector.domain.planning.protocols import PlanDecision, PlanDecisionKind
from connector.domain.reporting.collector import ReportCollector


@dataclass
class FakePolicy:
    def decide(self, validated_entity, validation: ValidationRowResult) -> PlanDecision:
        identity = Identity(primary="match_key", values={"match_key": "A|B|C|1"})
        if validated_entity == "skip":
            return PlanDecision(
                kind=PlanDecisionKind.SKIP,
                identity=identity,
                warnings=[ValidationErrorItem(stage=DiagnosticStage.PLAN, code="W", field=None, message="warn")],
            )
        if validated_entity == "conflict":
            return PlanDecision(
                kind=PlanDecisionKind.CONFLICT,
                identity=identity,
            )
        return PlanDecision(
            kind=PlanDecisionKind.CREATE,
            identity=identity,
            desired_state={"email": "a@b.c"},
            changes={},
            resource_id="id-1",
            source_ref={"match_key": "A|B|C|1"},
        )


def _make_validation(line_no: int) -> ValidationRowResult:
    return ValidationRowResult(
        line_no=line_no,
        match_key="A|B|C|1",
        match_key_complete=True,
        usr_org_tab_num=None,
        row_ref=None,
    )


def test_generic_planner_creates_plan_item():
    report = ReportCollector(run_id="r", command="plan-test")
    builder = PlanBuilder(
        include_skipped_in_report=True,
        report_items_limit=10,
        identity_label="match_key",
        conflict_code="CONFLICT",
        conflict_field="match_key",
        report=report,
    )
    planner = GenericPlanner(policy=FakePolicy(), builder=builder)
    planner.plan_validated_row("create", _make_validation(1), warnings=[])
    result = builder.build()
    assert result.items[0]["op"] == "create"
    assert result.items[0]["resource_id"] == "id-1"


def test_generic_planner_skip_adds_report_item():
    report = ReportCollector(run_id="r", command="plan-test")
    builder = PlanBuilder(
        include_skipped_in_report=True,
        report_items_limit=10,
        identity_label="match_key",
        conflict_code="CONFLICT",
        conflict_field="match_key",
        report=report,
    )
    planner = GenericPlanner(policy=FakePolicy(), builder=builder)
    planner.plan_validated_row("skip", _make_validation(2), warnings=[])
    builder.build()
    assert report.items[0].status == "SKIPPED"
    assert report.items[0].diagnostics


def test_generic_planner_conflict_marks_failed():
    report = ReportCollector(run_id="r", command="plan-test")
    builder = PlanBuilder(
        include_skipped_in_report=True,
        report_items_limit=10,
        identity_label="match_key",
        conflict_code="CONFLICT",
        conflict_field="match_key",
        report=report,
    )
    planner = GenericPlanner(policy=FakePolicy(), builder=builder)
    planner.plan_validated_row("conflict", _make_validation(3), warnings=[])
    result = builder.build()
    assert result.summary.failed_rows == 1
