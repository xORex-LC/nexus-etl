import json
import logging
from pathlib import Path

from typer.testing import CliRunner

from connector.importApplyService import ImportApplyService
from connector.planModels import Plan, PlanItem, PlanMeta, PlanSummary
from connector.planReader import readPlanFile
from connector.userApi import UserApi
from connector.userPayloadBuilder import buildUserUpsertPayload
from connector.cli import app
from connector.ankeyApiClient import ApiError

runner = CliRunner()


class DummyUserApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def upsertUser(self, resourceId: str, payload: dict):
        self.calls.append((resourceId, payload))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _make_plan(items: list[PlanItem]) -> Plan:
    return Plan(
        meta=PlanMeta(run_id="r1", generated_at=None, csv_path=None, plan_path=None, include_deleted_users=False),
        summary=PlanSummary(rows_total=len(items), planned_create=0, planned_update=0, skipped=0, failed=0),
        items=items,
    )


def test_plan_reader_reads_items(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "meta": {"run_id": "r1", "generated_at": "now", "csv_path": "a.csv"},
                "summary": {"rows_total": 1, "planned_create": 1, "planned_update": 0, "skipped": 0, "failed": 0},
                "items": [
                    {
                        "row_id": "line:1",
                        "line_no": 1,
                        "action": "create",
                        "match_key": "A|B|C|1",
                        "new_id": "id-1",
                        "desired": {"email": "a@b.c"},
                        "diff": {"mail": {"from": None, "to": "a@b.c"}},
                        "errors": [],
                        "warnings": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan = readPlanFile(str(plan_path))
    assert plan.items[0].action == "create"
    assert plan.items[0].new_id == "id-1"


def test_payload_builder_contains_exact_keys():
    payload = buildUserUpsertPayload(
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


def test_user_api_put_path_and_query():
    calls = {}

    class FakeClient:
        def requestJson(self, method, path, params=None, jsonBody=None):
            calls["method"] = method
            calls["path"] = path
            calls["params"] = params
            calls["json"] = jsonBody
            return 200, {"ok": True}

    api = UserApi(FakeClient())
    status, _ = api.upsertUser("abc", {"k": "v"})
    assert status == 200
    assert calls["method"] == "PUT"
    assert calls["path"].endswith("/ankey/managed/user/abc")
    assert calls["params"] == {"_prettyPrint": "true", "decrypt": "false"}


def test_import_apply_stop_on_first_error():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            action="create",
            match_key="A",
            existing_id=None,
            new_id="id-1",
            desired={
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
            diff={},
            errors=[],
            warnings=[],
        ),
        PlanItem(
            row_id="line:2",
            line_no=2,
            action="update",
            match_key="B",
            existing_id="id-2",
            new_id=None,
            desired={
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
            diff={},
            errors=[],
            warnings=[],
        ),
    ]
    plan = _make_plan(items)
    service = ImportApplyService(DummyUserApi([Exception("boom")]))
    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())
    report = type(
        "R", (), {"items": [], "summary": type("S", (), {"created": 0, "updated": 0, "skipped": 0, "failed": 0})()}
    )
    code = service.applyPlan(
        plan=plan,
        logger=logger,
        report=report,
        run_id="r",
        stop_on_first_error=True,
        max_actions=None,
        dry_run=False,
        report_items_limit=10,
        report_items_success=True,
        resource_exists_retries=0,
    )
    assert code == 1
    assert report.summary.failed == 1


def test_import_apply_max_actions_limits_requests():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            action="create",
            match_key="A",
            existing_id=None,
            new_id="id-1",
            desired={
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
            diff={},
            errors=[],
            warnings=[],
        ),
        PlanItem(
            row_id="line:2",
            line_no=2,
            action="create",
            match_key="B",
            existing_id=None,
            new_id="id-2",
            desired={
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
            diff={},
            errors=[],
            warnings=[],
        ),
    ]
    plan = _make_plan(items)
    user_api = DummyUserApi([(200, {"ok": True}), (200, {"ok": True})])
    service = ImportApplyService(user_api)
    logger = logging.getLogger("test2")
    logger.addHandler(logging.NullHandler())
    report = type(
        "R", (), {"items": [], "summary": type("S", (), {"created": 0, "updated": 0, "skipped": 0, "failed": 0})()}
    )
    service.applyPlan(
        plan=plan,
        logger=logger,
        report=report,
        run_id="r",
        stop_on_first_error=False,
        max_actions=1,
        dry_run=False,
        report_items_limit=10,
        report_items_success=True,
        resource_exists_retries=0,
    )
    assert len(user_api.calls) == 1


def test_import_apply_resource_exists_retries():
    items = [
        PlanItem(
            row_id="line:1",
            line_no=1,
            action="create",
            match_key="A",
            existing_id=None,
            new_id="id-1",
            desired={
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
            diff={},
            errors=[],
            warnings=[],
        )
    ]
    plan = _make_plan(items)
    user_api = DummyUserApi(
        [
            ApiError("HTTP 403", status_code=403, body_snippet="resourceExists"),
            (200, {"ok": True}),
        ]
    )
    service = ImportApplyService(user_api)
    logger = logging.getLogger("test3")
    logger.addHandler(logging.NullHandler())
    report = type(
        "R", (), {"items": [], "summary": type("S", (), {"created": 0, "updated": 0, "skipped": 0, "failed": 0})()}
    )
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
        resource_exists_retries=1,
    )
    assert code == 0
    assert report.summary.created == 1


def test_import_apply_requires_csv_or_plan(tmp_path: Path):
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
                "meta": {"run_id": "r1", "generated_at": "now"},
                "summary": {"rows_total": 2, "planned_create": 1, "planned_update": 1, "skipped": 0, "failed": 0},
                "items": [
                    {
                        "row_id": "line:1",
                        "line_no": 1,
                        "action": "create",
                        "match_key": "A|B|C|1",
                        "new_id": "id-1",
                        "desired": {
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
                        "diff": {},
                        "errors": [],
                        "warnings": [],
                    },
                    {
                        "row_id": "line:2",
                        "line_no": 2,
                        "action": "update",
                        "match_key": "A|B|C|2",
                        "existing_id": "id-2",
                        "desired": {
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
                        "diff": {},
                        "errors": [],
                        "warnings": [],
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
