import json
from pathlib import Path
from typing import Callable

import httpx
from typer.testing import CliRunner

from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.handlers.registry import CacheHandlerRegistry
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.repository import SqliteCacheRepository
from connector.main import app

runner = CliRunner()


def make_transport(responder: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(responder)


def patch_client_with_transport(monkeypatch, transport: httpx.BaseTransport):
    import connector.main as cli_module
    from connector.infra.http.ankey_client import AnkeyApiClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return AnkeyApiClient(*args, **kwargs)

    monkeypatch.setattr(cli_module, "AnkeyApiClient", factory)


def test_check_api_ok(monkeypatch, tmp_path: Path):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"ok": True}])

    transport = make_transport(responder)
    patch_client_with_transport(monkeypatch, transport)

    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "check-ok",
            "check-api",
        ],
    )
    assert result.exit_code == 0
    report_path = report_dir / "report_check-api_check-ok.json"
    assert report_path.exists()


def test_check_api_401(monkeypatch, tmp_path: Path):
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

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
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "check-401",
            "check-api",
        ],
    )
    assert result.exit_code == 2


def test_cache_refresh_from_api_two_pages(monkeypatch, tmp_path: Path):
    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        if path.endswith("/organization"):
            if page == 1:
                return httpx.Response(
                    200,
                    json={"items": [{"_ouid": 1, "name": "Org1"}, {"_ouid": 2, "name": "Org2"}]},
                )
            return httpx.Response(200, json={"items": []})
        if path.endswith("/user"):
            if page == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "_id": "u1",
                                "_ouid": 11,
                                "firstName": "A",
                                "lastName": "B",
                                "middleName": "C",
                                "personnelNumber": "1",
                                "mail": "u1@example.com",
                                "userName": "user1",
                                "usrOrgTabNum": "TAB-1",
                                "organization_id": 1,
                            }
                        ]
                    },
                )
            if page == 2:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "_id": "u2",
                                "_ouid": 22,
                                "firstName": "D",
                                "lastName": "E",
                                "middleName": "F",
                                "personnelNumber": "2",
                                "mail": "u2@example.com",
                                "userName": "user2",
                                "usrOrgTabNum": "TAB-2",
                                "organization_id": 1,
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"items": []})
        return httpx.Response(404)

    transport = make_transport(responder)
    patch_client_with_transport(monkeypatch, transport)

    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "api-refresh",
            "cache",
            "refresh",
            "--page-size",
            "1",
        ],
    )

    assert result.exit_code == 0
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        engine = SqliteEngine(conn)
        registry = CacheHandlerRegistry()
        for spec in list_cache_specs():
            registry.register(GenericCacheHandler(spec))
        repo = SqliteCacheRepository(engine, registry)
        users_count = repo.count("employees")
        org_count = repo.count("organizations")
    finally:
        conn.close()
    assert users_count == 2
    assert org_count == 2

    report_path = report_dir / "report_cache-refresh_api-refresh.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["rows_blocked"] == 0
    assert report["context"]["cache_refresh"]["by_dataset"]["employees"]["pages"] == 2
    assert report["context"]["cache_refresh"]["by_dataset"]["organizations"]["pages"] == 1


def test_cache_refresh_skips_deleted_users(monkeypatch, tmp_path: Path):
    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/organization"):
            return httpx.Response(200, json={"result": []})
        if path.endswith("/user"):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "_id": "u1",
                            "_ouid": 11,
                            "firstName": "A",
                            "lastName": "B",
                            "middleName": "C",
                            "personnelNumber": "1",
                            "accountStatus": "deleted",
                            "mail": "u1@example.com",
                            "userName": "user1",
                            "usrOrgTabNum": "TAB-1",
                            "organization_id": 1,
                        },
                        {
                            "_id": "u2",
                            "_ouid": 22,
                            "firstName": "D",
                            "lastName": "E",
                            "middleName": "F",
                            "personnelNumber": "2",
                            "deletionDate": "2025-01-01",
                            "mail": "u2@example.com",
                            "userName": "user2",
                            "usrOrgTabNum": "TAB-2",
                            "organization_id": 1,
                        },
                        {
                            "_id": "u3",
                            "_ouid": 33,
                            "firstName": "G",
                            "lastName": "H",
                            "middleName": "I",
                            "personnelNumber": "3",
                            "mail": "u3@example.com",
                            "userName": "user3",
                            "usrOrgTabNum": "TAB-3",
                            "organization_id": 1,
                        },
                    ]
                },
            )
        return httpx.Response(404)

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
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "skip-del",
            "cache",
            "refresh",
        ],
    )
    assert result.exit_code == 0
    report_path = tmp_path / "reports" / "report_cache-refresh_skip-del.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["context"]["cache_refresh"]["total"]["skipped"] == 2


def test_retry_on_500_then_ok(monkeypatch, tmp_path: Path):
    calls = {"user": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/organization"):
            return httpx.Response(200, json={"items": []})
        if path.endswith("/user"):
            calls["user"] += 1
            if calls["user"] == 1:
                return httpx.Response(500, text="fail")
            return httpx.Response(
                200,
                json={
                        "items": [
                            {
                                "_id": "u1",
                                "_ouid": 11,
                                "firstName": "A",
                                "lastName": "B",
                                "middleName": "C",
                                "personnelNumber": "1",
                                "mail": "u1@example.com",
                                "userName": "user1",
                                "usrOrgTabNum": "TAB-1",
                                "organization_id": 1,
                            }
                        ]
                    },
                )
        return httpx.Response(404)

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
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "retry-ok",
            "cache",
            "refresh",
            "--retries",
            "2",
        ],
    )
    assert result.exit_code == 0
    assert calls["user"] >= 2


def test_password_not_in_logs_or_report(monkeypatch, tmp_path: Path):
    secret = "VERY_SECRET_PASSWORD"

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/organization"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "_id": "u1",
                        "_ouid": 11,
                        "firstName": "A",
                        "lastName": "B",
                        "middleName": "C",
                        "personnelNumber": "1",
                        "mail": "u1@example.com",
                        "userName": "user1",
                        "usrOrgTabNum": "TAB-1",
                        "organization_id": 1,
                    }
                ]
            },
        )

    transport = make_transport(responder)
    patch_client_with_transport(monkeypatch, transport)

    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"

    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            secret,
            "--run-id",
            "no-secret",
            "cache",
            "refresh",
        ],
    )

    assert result.exit_code == 0
    report_path = report_dir / "report_cache-refresh_no-secret.json"
    log_path = log_dir / "cache-refresh_no-secret.log"
    assert report_path.exists()
    assert log_path.exists()
    assert secret not in report_path.read_text(encoding="utf-8")
    assert secret not in log_path.read_text(encoding="utf-8")
