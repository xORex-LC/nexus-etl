"""
Unit-тесты контракта ImportApplyService.apply_plan() → ApplyResult.
"""

from __future__ import annotations

from connector.delivery.commands.import_apply_dry_run_executor import DryRunExecutor
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.planning.record_ref import RecordRef
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.usecases.apply.models import ApplyResult, ApplySummary
from connector.usecases.apply.telemetry import NullApplyTelemetrySink
from connector.usecases.import_apply_service import ImportApplyService


class DummyExecutor:
    def __init__(self, result: ExecutionResult):
        self.result = result
        self.calls: list[RequestSpec] = []

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls.append(spec)
        return self.result


def _make_plan(items: list[PlanItem], *, skipped: int = 0) -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="r",
            generated_at=None,
            csv_path=None,
            plan_path=None,
            include_deleted=False,
            dataset="employees",
        ),
        summary=PlanSummary(
            rows_total=len(items),
            valid_rows=len(items),
            failed_rows=0,
            planned_create=sum(1 for i in items if i.op == "create"),
            planned_update=sum(1 for i in items if i.op == "update"),
            skipped=skipped,
        ),
        items=items,
    )


def _make_item(row_id: str = "line:1", line_no: int = 1, op: str = "create", target_id: str = "id-1") -> PlanItem:
    return PlanItem(
        row_id=row_id,
        line_no=line_no,
        op=op,
        target_id=target_id,
        desired_state={
            "email": "u@example.com",
            "last_name": "L",
            "first_name": "F",
            "middle_name": "M",
            "is_logon_disable": False,
            "user_name": "u",
            "phone": "+1",
            "password": "secret",
            "personnel_number": "10",
            "manager_id": None,
            "organization_id": 5,
            "position": "P",
            "usr_org_tab_num": "TAB",
        },
        changes={},
        source_ref={"match_key": "mk"},
    )


def _ok_executor() -> DummyExecutor:
    return DummyExecutor(ExecutionResult(ok=True, answer_code=200, response_payload={"_id": "id-1"}))


def _fail_executor(code: SystemErrorCode = SystemErrorCode.DATA_INVALID) -> DummyExecutor:
    return DummyExecutor(ExecutionResult(ok=False, answer_code=400, error_code=code, error_message="bad request"))


def _make_adapter():
    from connector.datasets.registry import get_spec
    return get_spec("employees").get_apply_adapter()


def _make_service(executor: DummyExecutor) -> ImportApplyService:
    return ImportApplyService(executor)


def _apply(service: ImportApplyService, plan: Plan, *, catalog, **kwargs) -> ApplyResult:
    defaults = dict(
        catalog=catalog,
        apply_adapter=_make_adapter(),
        stop_on_first_error=False,
        max_actions=None,
        max_item_outcomes=100,
    )
    defaults.update(kwargs)
    return service.apply_plan(plan=plan, **defaults)


# --- Тесты ---


class TestApplyResultContract:
    def test_returns_apply_result(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(_make_service(_ok_executor()), _make_plan([_make_item()]), catalog=catalog)
        assert isinstance(result, ApplyResult)
        assert isinstance(result.summary, ApplySummary)

    def test_all_ok_primary_code_is_ok(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(3)]
        result = _apply(_make_service(_ok_executor()), _make_plan(items), catalog=catalog)
        assert result.primary_code == SystemErrorCode.OK
        assert not result.fatal_error
        assert result.summary.created == 3
        assert result.summary.failed == 0

    def test_all_failed_primary_code_not_ok(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(2)]
        result = _apply(_make_service(_fail_executor()), _make_plan(items), catalog=catalog)
        assert result.primary_code != SystemErrorCode.OK
        assert result.summary.failed == 2
        assert result.summary.created == 0

    def test_error_stats_populated(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(_make_service(_fail_executor()), _make_plan([_make_item()]), catalog=catalog)
        assert result.summary.error_stats
        assert sum(result.summary.error_stats.values()) > 0

    def test_item_outcomes_bounded_by_max_item_outcomes(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(10)]
        result = _apply(
            _make_service(_fail_executor()),
            _make_plan(items),
            catalog=catalog,
            max_item_outcomes=3,
        )
        assert len(result.item_outcomes) == 3
        assert result.summary.failed == 10

    def test_item_outcomes_empty_when_all_ok(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(5)]
        result = _apply(_make_service(_ok_executor()), _make_plan(items), catalog=catalog)
        assert len(result.item_outcomes) == 0

    def test_item_outcome_has_record_ref(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(
            _make_service(_fail_executor()),
            _make_plan([_make_item(row_id="r1", line_no=42)]),
            catalog=catalog,
        )
        assert len(result.item_outcomes) == 1
        ref = result.item_outcomes[0].record_ref
        assert isinstance(ref, RecordRef)
        assert ref.row_id == "r1"
        assert ref.line_no == 42

    def test_item_outcome_diagnostics_are_tuple(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(_make_service(_fail_executor()), _make_plan([_make_item()]), catalog=catalog)
        outcome = result.item_outcomes[0]
        assert isinstance(outcome.diagnostics, tuple)
        assert len(outcome.diagnostics) >= 1

    def test_all_codes_is_sorted_tuple(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(_make_service(_fail_executor()), _make_plan([_make_item()]), catalog=catalog)
        assert isinstance(result.all_codes, tuple)
        values = [c.value for c in result.all_codes]
        assert values == sorted(values)

    def test_skipped_from_plan_summary(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        result = _apply(_make_service(_ok_executor()), _make_plan([_make_item()], skipped=5), catalog=catalog)
        assert result.summary.skipped == 5

    def test_items_total_matches_processed(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(4)]
        result = _apply(_make_service(_ok_executor()), _make_plan(items), catalog=catalog)
        assert result.summary.items_total == 4

    def test_max_actions_limits_processing(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(10)]
        result = _apply(_make_service(_ok_executor()), _make_plan(items), catalog=catalog, max_actions=3)
        assert result.summary.items_total == 3
        assert result.summary.created == 3


class TestApplyDryRun:
    def test_dry_run_executor_keeps_apply_path_and_calls_adapter(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        class SpyAdapter:
            def __init__(self):
                self.calls = 0

            def to_request(self, item: PlanItem) -> RequestSpec:
                self.calls += 1
                return RequestSpec.operation(
                    alias="users.upsert",
                    payload={"target_id": item.target_id},
                    params={"target_id": item.target_id},
                )

        adapter = SpyAdapter()
        service = ImportApplyService(DryRunExecutor())
        result = _apply(service, _make_plan([_make_item()]), catalog=catalog, apply_adapter=adapter)

        assert adapter.calls == 1
        assert result.primary_code == SystemErrorCode.OK
        assert result.summary.created == 1
        assert result.summary.failed == 0

    def test_success_side_effects_can_be_disabled(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        class SpyIdentitySyncer:
            def __init__(self) -> None:
                self.calls = 0

            def id_field_for(self, dataset: str) -> str:
                _ = dataset
                return "_id"

            def sync(self, dataset: str, resolved_id, key_values) -> None:
                _ = (dataset, resolved_id, key_values)
                self.calls += 1

        class SpyRetention:
            def __init__(self) -> None:
                self.calls = 0

            def on_apply_success(self, **kwargs):
                _ = kwargs
                self.calls += 1
                return {"deleted": 1}

        identity_syncer = SpyIdentitySyncer()
        retention = SpyRetention()
        service = ImportApplyService(
            executor=DryRunExecutor(),
            identity_syncer=identity_syncer,
            secret_retention=retention,
            allow_post_success_side_effects=False,
        )

        result = _apply(service, _make_plan([_make_item()]), catalog=catalog)

        assert result.primary_code == SystemErrorCode.OK
        assert identity_syncer.calls == 0
        assert retention.calls == 0
        assert result.summary.retention_stats == {}


class TestApplyStopOnFirstError:
    def test_stops_after_first_failure(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(5)]
        result = _apply(
            _make_service(_fail_executor()),
            _make_plan(items),
            catalog=catalog,
            stop_on_first_error=True,
        )
        assert result.summary.failed == 1
        assert result.summary.items_total == 1


class TestTelemetrySink:
    def test_telemetry_receives_events(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        events: list[str] = []

        class CaptureSink:
            def on_item_ok(self, **kw):
                events.append("ok")
            def on_item_warn(self, **kw):
                events.append("warn")
            def on_item_error(self, **kw):
                events.append("error")
            def on_summary(self, **kw):
                events.append("summary")

        service = _make_service(_ok_executor())
        _apply(service, _make_plan([_make_item()]), catalog=catalog, telemetry=CaptureSink())
        assert "ok" in events
        assert "summary" in events

    def test_error_telemetry_on_failure(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        events: list[str] = []

        class CaptureSink:
            def on_item_ok(self, **kw):
                events.append("ok")
            def on_item_warn(self, **kw):
                events.append("warn")
            def on_item_error(self, **kw):
                events.append("error")
            def on_summary(self, **kw):
                events.append("summary")

        service = _make_service(_fail_executor())
        _apply(service, _make_plan([_make_item()]), catalog=catalog, telemetry=CaptureSink())
        assert "error" in events
        assert "summary" in events
        assert "ok" not in events

    def test_null_sink_works(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        service = _make_service(_ok_executor())
        result = _apply(service, _make_plan([_make_item()]), catalog=catalog, telemetry=NullApplyTelemetrySink())
        assert result.primary_code == SystemErrorCode.OK


class TestOutcomesTruncated:
    def test_outcomes_truncated_when_buffer_full(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(10)]
        result = _apply(_make_service(_fail_executor()), _make_plan(items), catalog=catalog, max_item_outcomes=3)
        assert result.outcomes_truncated is True
        assert len(result.item_outcomes) == 3

    def test_outcomes_not_truncated_when_buffer_not_full(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(3)]
        result = _apply(_make_service(_fail_executor()), _make_plan(items), catalog=catalog, max_item_outcomes=10)
        assert result.outcomes_truncated is False
        assert len(result.item_outcomes) == 3

    def test_outcomes_truncated_with_zero_limit(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(3)]
        result = _apply(_make_service(_fail_executor()), _make_plan(items), catalog=catalog, max_item_outcomes=0)
        assert result.outcomes_truncated is True
        assert len(result.item_outcomes) == 0

    def test_outcomes_not_truncated_when_all_ok(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        items = [_make_item(row_id=f"line:{i}", line_no=i) for i in range(5)]
        result = _apply(_make_service(_ok_executor()), _make_plan(items), catalog=catalog, max_item_outcomes=3)
        assert result.outcomes_truncated is False
        assert len(result.item_outcomes) == 0


class TestTargetIdMissing:
    def test_missing_target_id_fails(self, employees_registry_path):
        catalog = build_catalog("employees", strict=True)
        item = _make_item(target_id=None)
        result = _apply(_make_service(_ok_executor()), _make_plan([item]), catalog=catalog)
        assert result.summary.failed == 1
        assert result.item_outcomes[0].status == "FAILED"
