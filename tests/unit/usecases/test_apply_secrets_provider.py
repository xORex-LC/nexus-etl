from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.usecases.import_apply_service import ImportApplyService
from connector.infra.secrets.dict_provider import DictSecretProvider
from connector.infra.secrets.null_provider import NullSecretProvider
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec, RequestExecutorProtocol
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.employees.spec import make_employees_spec

CATALOG = build_catalog("employees", strict=True)


class DummyExecutor(RequestExecutorProtocol):
    def __init__(self):
        self.last_spec: RequestSpec | None = None
        self.calls = 0

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls += 1
        self.last_spec = spec
        return ExecutionResult(ok=True, answer_code=200, response_payload={"ok": True})


def make_plan(op: str, desired_state: dict, secret_fields: list[str] | None = None) -> Plan:
    meta = PlanMeta(run_id="r1", generated_at="now", dataset="employees", csv_path=None, plan_path=None, include_deleted=None)
    summary = PlanSummary(rows_total=1, valid_rows=1, failed_rows=0, planned_create=1 if op == "create" else 0, planned_update=1 if op == "update" else 0, skipped=0)
    item = PlanItem(
        row_id="row1",
        line_no=1,
        op=op,
        target_id="user-1",
        desired_state=desired_state,
        changes={},
        source_ref={},
        secret_fields=secret_fields or [],
    )
    return Plan(meta=meta, summary=summary, items=[item])


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
    adapter = make_employees_spec(secrets=provider).get_apply_adapter()
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor)
    plan = make_plan("create", base_desired_state(with_password=False), secret_fields=["password"])

    result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        apply_adapter=adapter,
        stop_on_first_error=False,
        max_actions=None,
        max_item_outcomes=10,
    )

    assert result.primary_code == SystemErrorCode.OK
    assert executor.calls == 1
    assert executor.last_spec is not None
    assert executor.last_spec.payload.get("password") == "secret123"
    assert plan.items[0].desired_state.get("password") == ""


def test_apply_create_fails_when_secret_missing():
    provider = NullSecretProvider()
    adapter = make_employees_spec(secrets=provider).get_apply_adapter()
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor)
    plan = make_plan("create", base_desired_state(with_password=False), secret_fields=["password"])

    result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        apply_adapter=adapter,
        stop_on_first_error=False,
        max_actions=None,
        max_item_outcomes=10,
    )

    assert result.primary_code != SystemErrorCode.OK
    assert executor.calls == 0
    assert result.item_outcomes, "должен быть outcome с ошибкой"
    diag = result.item_outcomes[0].diagnostics[0]
    assert diag.code == "SECRET_REQUIRED"


class CountingProvider(NullSecretProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def get_secret(self, **kwargs):
        self.calls += 1
        return None


def test_apply_update_does_not_request_secret():
    provider = CountingProvider()
    adapter = make_employees_spec(secrets=provider).get_apply_adapter()
    executor = DummyExecutor()
    service = ImportApplyService(executor=executor)
    plan = make_plan("update", base_desired_state(with_password=False), secret_fields=[])

    result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        apply_adapter=adapter,
        stop_on_first_error=False,
        max_actions=None,
        max_item_outcomes=10,
    )

    assert result.primary_code == SystemErrorCode.OK
    assert provider.calls == 0
    assert executor.calls == 1
    assert executor.last_spec is not None
    assert "password" not in executor.last_spec.payload
