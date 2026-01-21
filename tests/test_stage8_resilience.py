import httpx
import pytest
from typer.testing import CliRunner

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.main import app
from connector.usecases.import_apply_service import ImportApplyService
from connector.planModels import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.error_codes import ErrorCode
from connector.domain.ports.execution import ExecutionResult, RequestSpec
from connector.datasets.employees.apply_adapter import EmployeesApplyAdapter

runner = CliRunner()

def make_transport(responder):
    return httpx.MockTransport(responder)

def patch_client_with_transport(monkeypatch, transport: httpx.BaseTransport):
    import connector.main as cli_module
    import connector.usecases.cache_refresh_service as cache_service_module

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return AnkeyApiClient(*args, **kwargs)

    monkeypatch.setattr(cli_module, "AnkeyApiClient", factory)
    monkeypatch.setattr(cache_service_module, "AnkeyApiClient", factory)


class DummyExecutor:
    def __init__(self, result: ExecutionResult):
        self.result = result
        self.calls: list[RequestSpec] = []

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls.append(spec)
        return self.result


class DummySpec:
    def __init__(self, adapter):
        self.adapter = adapter

    def get_apply_adapter(self):
        return self.adapter

def test_cache_refresh_max_pages_exceeded(monkeypatch, tmp_path):
    def responder(request: httpx.Request) -> httpx.Response:
        # always return non-empty page to trigger max_pages guard
        return httpx.Response(200, json={"result": [{"_ouid": 1}]})

    transport = make_transport(responder)
    patch_client_with_transport(monkeypatch, transport)

    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--page-size",
            "1",
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--max-pages",
            "1",
            "cache",
            "refresh",
        ],
    )
    # max_pages exceeded should lead to exit code 2
    assert result.exit_code == 2

def test_api_client_invalid_json(monkeypatch):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = AnkeyApiClient(
        baseUrl="https://api.local",
        username="u",
        password="p",
        timeoutSeconds=1,
        retries=0,
        retryBackoffSeconds=0,
        transport=make_transport(responder),
    )
    with pytest.raises(ApiError) as excinfo:
        client.getJson("/path")
    assert excinfo.value.code == "INVALID_JSON"
    assert not excinfo.value.retryable

def test_import_apply_error_stats():
    class DummyUserApi:
        def __init__(self):
            self.client = type("C", (), {"getRetryAttempts": lambda self: 0})()

        def upsertUser(self, resourceId, payload):
            raise ApiError("HTTP 400", status_code=400)

    plan = Plan(
        meta=PlanMeta(
            run_id="r",
            generated_at=None,
            csv_path=None,
            plan_path=None,
            include_deleted_users=False,
            dataset="employees",
        ),
        summary=PlanSummary(
            rows_total=1,
            valid_rows=1,
            failed_rows=0,
            planned_create=1,
            planned_update=0,
            skipped=0,
        ),
        items=[
            PlanItem(
                row_id="line:1",
                line_no=1,
                entity_type="employee",
                op="create",
                resource_id="id-1",
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
        ],
    )
    report = type(
        "R",
        (),
        {
            "items": [],
            "summary": type(
                "S",
                (),
                {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "error_stats": {}, "retries_total": 0},
            )(),
            "meta": type("M", (), {"items_truncated": False})(),
        },
    )
    import logging

    logger = logging.getLogger("dummy")
    logger.addHandler(logging.NullHandler())
    executor = DummyExecutor(
        ExecutionResult(ok=False, status_code=400, error_code=ErrorCode.HTTP_ERROR, error_message="HTTP 400")
    )
    adapter = EmployeesApplyAdapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    code = service.applyPlan(
        plan=plan,
        logger=logger,
        report=report,
        run_id="r",
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        resource_exists_retries=0,
    )
    assert code == 1
    assert report.summary.error_stats.get("HTTP_ERROR") == 1
