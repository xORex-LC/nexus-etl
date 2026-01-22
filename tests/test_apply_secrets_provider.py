from types import SimpleNamespace

from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.usecases.import_apply_service import ImportApplyService
from connector.infra.secrets.dict_provider import DictSecretProvider
from connector.infra.secrets.null_provider import NullSecretProvider
from connector.domain.ports.execution import ExecutionResult, RequestSpec, RequestExecutorProtocol
from connector.domain.error_codes import ErrorCode


class DummyExecutor(RequestExecutorProtocol):
    def __init__(self):
        self.last_spec: RequestSpec | None = None
        self.calls = 0

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls += 1
        self.last_spec = spec
        return ExecutionResult(ok=True, status_code=200, response_json={"ok": True})


def make_plan(op: str, desired_state: dict) -> Plan:
    meta = PlanMeta(run_id="r1", generated_at="now", dataset="employees", csv_path=None, plan_path=None, include_deleted=None)
    summary = PlanSummary(rows_total=1, valid_rows=1, failed_rows=0, planned_create=1 if op == "create" else 0, planned_update=1 if op == "update" else 0, skipped=0)
    item = PlanItem(
        row_id="row1",
        line_no=1,
        op=op,
        resource_id="user-1",
        desired_state=desired_state,
        changes={},
        source_ref={},
    )
    return Plan(meta=meta, summary=summary, items=[item])


def make_report():
    return SimpleNamespace(
        meta=SimpleNamespace(items_truncated=False, plan_file=None),
        summary=SimpleNamespace(created=0, updated=0, skipped=0, failed=0, error_stats={}),
        items=[],
    )


class DummyLogger:
    def log(self, *args, **kwargs):
        return None


def base_desired_state(with_password: bool = False) -> dict:
    state = {
        "email": "a@b.c",
        "last_name": "L",
        "first_name": "F",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "user1",
        "phone": "123",
        "password": "p" if with_password else "",
        "personnel_number": "pn1",
        "organization_id": 1,
        "position": "pos",
        "usr_org_tab_num": "tab1",
    }
    return state


def test_apply_create_uses_secret_provider_when_missing_password():
    provider = DictSecretProvider({("employees", "password", "row1", 1): "secret123"})
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor, secrets=provider)
    plan = make_plan("create", base_desired_state(with_password=False))
    report = make_report()

    code = service.applyPlan(
        plan=plan,
        logger=DummyLogger(),
        report=report,
        run_id="run1",
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        resource_exists_retries=0,
    )

    assert code == 0
    assert executor.calls == 1
    assert executor.last_spec is not None
    assert executor.last_spec.payload.get("password") == "secret123"
    # План не модифицируется секретом
    assert plan.items[0].desired_state.get("password") == ""


def test_apply_create_fails_when_secret_missing():
    provider = NullSecretProvider()
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor, secrets=provider)
    plan = make_plan("create", base_desired_state(with_password=False))
    report = make_report()

    code = service.applyPlan(
        plan=plan,
        logger=DummyLogger(),
        report=report,
        run_id="run1",
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        resource_exists_retries=0,
    )

    assert code == 1
    assert executor.calls == 0
    assert report.items, "должна быть записана ошибка"
    err = report.items[0]["errors"][0]
    assert err["code"] == ErrorCode.SECRET_REQUIRED.value


class CountingProvider(NullSecretProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def get_secret(self, **kwargs):
        self.calls += 1
        return None


def test_apply_update_does_not_request_secret():
    provider = CountingProvider()
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor, secrets=provider)
    plan = make_plan("update", base_desired_state(with_password=True))
    report = make_report()

    code = service.applyPlan(
        plan=plan,
        logger=DummyLogger(),
        report=report,
        run_id="run1",
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        resource_exists_retries=0,
    )

    assert code == 0
    assert provider.calls == 0
    assert executor.calls == 1
