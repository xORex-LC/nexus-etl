import json
from pathlib import Path

from typer.testing import CliRunner

from connector.usecases.import_apply_service import ImportApplyService
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.reporting.collector import ReportCollector
from connector.delivery.presenters.apply_report_presenter import ApplyReportPresenter
from connector.datasets.employees.spec import make_employees_spec
from connector.main import app
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)

runner = CliRunner()

class DummyExecutor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls.append(spec)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class DummySpec:
    def __init__(self, adapter):
        self.adapter = adapter

    def get_apply_adapter(self):
        return self.adapter

def _make_plan(items: list[PlanItem]) -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="r1",
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
            planned_create=0,
            planned_update=0,
            skipped=0,
        ),
        items=items,
    )

def test_plan_reader_reads_items(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "meta": {"run_id": "r1", "generated_at": "now", "csv_path": "a.csv", "dataset": "employees"},
                "summary": {
                    "rows_total": 1,
                    "valid_rows": 1,
                    "failed_rows": 0,
                    "planned_create": 1,
                    "planned_update": 0,
                    "skipped": 0,
                },
                "items": [
                    {
                        "row_id": "line:1",
                        "line_no": 1,
                            "dataset": "employees",
                            "op": "create",
                            "target_id": "id-1",
                        "desired_state": {"email": "a@b.c"},
                        "changes": {"mail": "a@b.c"},
                        "source_ref": {"match_key": "A|B|C|1"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan = readPlanFile(str(plan_path))
    assert plan.items[0].op == "create"
    assert plan.items[0].target_id == "id-1"

def test_payload_builder_contains_exact_keys():
    payload = build_user_upsert_payload(
        {
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
        }
    )
    assert set(payload.keys()) == {
        "mail",
        "lastName",
        "firstName",
        "middleName",
        "isLogonDisabled",
        "userName",
        "phone",
        "password",
        "personnelNumber",
        "managerId",
        "organization_id",
        "position",
        "avatarId",
        "usrOrgTabNum",
    }

def test_apply_adapter_builds_request():
    adapter = make_employees_spec().get_apply_adapter()
    item = PlanItem(
        row_id="line:1",
        line_no=1,
        op="create",
        target_id="abc",
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
        source_ref={"match_key": "A"},
    )
    spec = adapter.to_request(item)
    assert spec.operation_alias == "users.upsert"
    assert spec.operation_params == {"target_id": "abc"}

def test_import_apply_stop_on_first_error():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            op="create",
            target_id="id-1",
            desired_state={
                "email": "a@b.c",
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
            source_ref={"match_key": "A"},
        ),
        PlanItem(
            row_id="line:2",
            line_no=2,
            op="update",
            target_id="id-2",
            desired_state={
                "email": "b@b.c",
                "last_name": "L",
                "first_name": "F",
                "middle_name": "M",
                "is_logon_disable": False,
                "user_name": "u2",
                "phone": "+2",
                "password": "secret",
                "personnel_number": "20",
                "manager_id": None,
                "organization_id": 5,
                "position": "P",
                "usr_org_tab_num": "TAB2",
            },
            changes={},
            source_ref={"match_key": "B"},
        ),
    ]
    plan = _make_plan(items)
    executor = DummyExecutor(
        [
            ExecutionResult(ok=False, answer_code=500, error_code=SystemErrorCode.INFRA_UNAVAILABLE, error_message="boom"),
        ]
    )
    adapter = make_employees_spec().get_apply_adapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    apply_result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        stop_on_first_error=True,
        max_actions=None,
        dry_run=False,
        max_item_outcomes=10,
    )
    assert apply_result.primary_code != SystemErrorCode.OK
    assert apply_result.summary.failed == 1

    report = ReportCollector(run_id="r", command="import-apply")
    ApplyReportPresenter.present(apply_result, report, plan)
    assert report.build().summary.ops.get("apply_failed", {}).get("failed") == 1

def test_import_apply_max_actions_limits_requests():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            op="create",
            target_id="id-1",
            desired_state={
                "email": "a@b.c",
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
            source_ref={"match_key": "A"},
        ),
        PlanItem(
            row_id="line:2",
            line_no=2,
            op="create",
            target_id="id-2",
            desired_state={
                "email": "b@b.c",
                "last_name": "L",
                "first_name": "F",
                "middle_name": "M",
                "is_logon_disable": False,
                "user_name": "u2",
                "phone": "+2",
                "password": "secret",
                "personnel_number": "20",
                "manager_id": None,
                "organization_id": 5,
                "position": "P",
                "usr_org_tab_num": "TAB2",
            },
            changes={},
            source_ref={"match_key": "B"},
        ),
    ]
    plan = _make_plan(items)
    executor = DummyExecutor(
        [
            ExecutionResult(ok=True, answer_code=200, response_payload={"ok": True}),
            ExecutionResult(ok=True, answer_code=200, response_payload={"ok": True}),
        ]
    )
    adapter = make_employees_spec().get_apply_adapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        stop_on_first_error=False,
        max_actions=1,
        dry_run=False,
        max_item_outcomes=10,
    )
    assert len(executor.calls) == 1

def test_import_apply_does_not_retry_resource_exists_in_usecase():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            op="create",
            target_id="id-1",
            desired_state={
                "email": "a@b.c",
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
            source_ref={"match_key": "A"},
        )
    ]
    plan = _make_plan(items)
    executor = DummyExecutor(
        [
            ExecutionResult(
                ok=False, answer_code=409, error_code=SystemErrorCode.CONFLICT, error_message="conflict", error_reason="resourceexists"
            ),
        ]
    )
    adapter = make_employees_spec().get_apply_adapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    apply_result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        max_item_outcomes=10,
    )
    assert apply_result.primary_code == SystemErrorCode.CONFLICT
    assert apply_result.summary.failed == 1
    assert len(executor.calls) == 1

def test_import_apply_requires_plan(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "import",
            "apply",
        ],
    )
    assert result.exit_code == 2

def test_import_apply_plan_happy_path(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "meta": {"run_id": "r1", "generated_at": "now", "dataset": "employees"},
                "summary": {
                    "rows_total": 2,
                    "valid_rows": 2,
                    "failed_rows": 0,
                    "planned_create": 1,
                    "planned_update": 1,
                    "skipped": 0,
                },
                "items": [
                    {
                        "row_id": "line:1",
                        "line_no": 1,
                            "dataset": "employees",
                            "op": "create",
                        "target_id": "id-1",
                        "desired_state": {
                            "email": "u1@example.com",
                            "last_name": "L",
                            "first_name": "F",
                            "middle_name": "M",
                            "is_logon_disable": False,
                            "user_name": "u1",
                            "phone": "+1",
                            "password": "secret",
                            "personnel_number": "10",
                            "manager_id": None,
                            "organization_id": 5,
                            "position": "P",
                            "usr_org_tab_num": "TAB",
                        },
                        "changes": {},
                        "source_ref": {"match_key": "A|B|C|1"},
                    },
                    {
                        "row_id": "line:2",
                        "line_no": 2,
                            "dataset": "employees",
                            "op": "update",
                        "target_id": "id-2",
                        "desired_state": {
                            "email": "u2@example.com",
                            "last_name": "L",
                            "first_name": "F",
                            "middle_name": "M",
                            "is_logon_disable": False,
                            "user_name": "u2",
                            "phone": "+2",
                            "password": "secret",
                            "personnel_number": "20",
                            "manager_id": None,
                            "organization_id": 5,
                            "position": "P",
                            "usr_org_tab_num": "TAB2",
                        },
                        "changes": {},
                        "source_ref": {"match_key": "A|B|C|2"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run_id = "apply-ok"
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            run_id,
            "import",
            "apply",
            "--plan",
            str(plan_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    report_path = tmp_path / "reports" / f"report_import-apply_{run_id}.json"
    assert report_path.exists()


def test_plan_builder_does_not_emit_dataset_in_items():
    from connector.domain.transform.matcher.match_models import ResolvedRow, ResolveOp
    from connector.domain.models import Identity, RowRef

    builder = PlanBuilder()
    resolved = ResolvedRow(
        row_ref=RowRef(line_no=1, row_id="r1", identity_primary="match_key", identity_value="A|B|C|1"),
        identity=Identity(primary="match_key", values={"match_key": "A|B|C|1"}),
        op=ResolveOp.CREATE,
        desired_state={"email": "a@b.c"},
        changes={},
        target_id="id-1",
    )
    builder.add_resolved(resolved)
    result = builder.build()
    assert "dataset" not in result.items[0]
    assert "entity_type" not in result.items[0]


def test_apply_report_items_include_dataset():
    dataset = "employees"
    plan = _make_plan(
        [
            PlanItem(
                row_id="r1",
                line_no=1,
                op="create",
                target_id="id-1",
                desired_state={
                    "email": "u@example.com",
                    "password": "secret",
                    "last_name": "L",
                    "first_name": "F",
                    "middle_name": "M",
                    "is_logon_disable": False,
                    "user_name": "user1",
                    "phone": "+1",
                    "personnel_number": "10",
                    "organization_id": 1,
                    "position": "P",
                    "usr_org_tab_num": "TAB",
                },
                changes={},
            )
        ]
    )
    executor = DummyExecutor(
        [
            ExecutionResult(ok=False, answer_code=500, error_code=SystemErrorCode.INFRA_UNAVAILABLE, error_message="boom"),
        ]
    )
    adapter = make_employees_spec().get_apply_adapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    apply_result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        max_item_outcomes=10,
    )
    assert apply_result.primary_code != SystemErrorCode.OK

    report = ReportCollector(run_id="r", command="import-apply")
    report.set_meta(dataset=dataset)
    ApplyReportPresenter.present(apply_result, report, plan)
    built = report.build()
    assert built.meta.dataset == dataset
    assert built.items
