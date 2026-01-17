import httpx
import pytest
from typer.testing import CliRunner

from connector.ankeyApiClient import AnkeyApiClient, ApiError
from connector.cli import app
from connector.importApplyService import ImportApplyService
from connector.planModels import Plan, PlanItem, PlanMeta, PlanSummary


runner = CliRunner()


def make_transport(responder):
    return httpx.MockTransport(responder)


def patch_client_with_transport(monkeypatch, transport: httpx.BaseTransport):
    import connector.cli as cli_module
    import connector.cacheService as cache_service_module

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return AnkeyApiClient(*args, **kwargs)

    monkeypatch.setattr(cli_module, "AnkeyApiClient", factory)
    monkeypatch.setattr(cache_service_module, "AnkeyApiClient", factory)


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
        meta=PlanMeta(run_id="r", generated_at=None, csv_path=None, plan_path=None, include_deleted_users=False),
        summary=PlanSummary(rows_total=1, planned_create=1, planned_update=0, skipped=0, failed=0),
        items=[
            PlanItem(
                row_id="line:1",
                line_no=1,
                action="create",
                match_key="mk",
                existing_id=None,
                new_id="id-1",
                desired={
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
                diff={},
                errors=[],
                warnings=[],
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
    service = ImportApplyService(DummyUserApi())
    code = service.applyPlan(
        plan=plan,
        logger=logger,
        report=report,
        run_id="r",
        stop_on_first_error=False,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        report_items_success=True,
        resource_exists_retries=0,
    )
    assert code == 1
    assert report.summary.error_stats.get("HTTP_400") == 1
