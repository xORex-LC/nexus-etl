import httpx
import pytest
from typer.testing import CliRunner

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.main import app
from connector.usecases.import_apply_service import ImportApplyService
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.datasets.employees.spec import make_employees_spec
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)

runner = CliRunner()

def make_transport(responder):
    return httpx.MockTransport(responder)

def patch_client_with_transport(monkeypatch, transport: httpx.BaseTransport):
    import connector.delivery.commands.cache_refresh as cache_refresh_command
    from connector.delivery.cli.bootstrap import (
        build_target_runtime_with_info as _build_real_runtime_with_info,
    )

    patched_transport = transport

    def factory(api_settings, *, transport=None, include_reader=True, runtime_mode=None):
        _ = transport
        return _build_real_runtime_with_info(
            api_settings,
            transport=patched_transport,
            include_reader=include_reader,
            runtime_mode=runtime_mode,
        )

    monkeypatch.setattr(cache_refresh_command, "build_target_runtime_with_info", factory)


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
        # Всегда возвращаем непустую страницу, чтобы сработал guard max_pages.
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
    # Превышение max_pages должно приводить к exit code 2.
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
            include_deleted=False,
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
            op="create",
            target_id="id-1",
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
    executor = DummyExecutor(
        ExecutionResult(ok=False, status_code=400, error_code=SystemErrorCode.DATA_INVALID, error_message="HTTP 400")
    )
    adapter = make_employees_spec().get_apply_adapter()
    service = ImportApplyService(executor, spec_resolver=lambda *args, **kwargs: DummySpec(adapter))
    result = service.apply_plan(
        plan=plan,
        catalog=CATALOG,
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        max_item_outcomes=10,
    )
    assert result.primary_code != SystemErrorCode.OK
    assert result.summary.error_stats.get("SINK_HTTP_ERROR") == 1
