from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from connector.config.app_settings import PathsSettings
from connector.datasets.employees.spec import make_employees_spec
from connector.delivery.cli.containers import build_secret_provider
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_models import Operation, Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.ports.target.execution import ExecutionResult, RequestExecutorProtocol, RequestSpec
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.config.app_settings import SqliteSettings, build_vault_db_config
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.usecases.apply.models import ApplyResult
from connector.usecases.import_apply_service import ImportApplyService

CATALOG = build_catalog("employees", strict=True)
DEFAULT_MATCH_KEY = "Doe|John|M|100"
DEFAULT_RUN_ID = "run-stage-05"


class _DummyExecutor(RequestExecutorProtocol):
    def __init__(self) -> None:
        self.calls: list[RequestSpec] = []

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        self.calls.append(spec)
        return ExecutionResult(ok=True, answer_code=200, response_payload={"ok": True})


def _paths(tmp_path: Path) -> PathsSettings:
    return PathsSettings(
        cache_dir=str(tmp_path / "cache"),
        log_dir=str(tmp_path / "logs"),
        report_dir=str(tmp_path / "reports"),
    )


def _base_desired_state(*, password: str = "") -> dict[str, object]:
    return {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+1111111",
        "password": password,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
    }


def _make_plan(
    *,
    op: str,
    secret_fields: list[str],
    run_id: str = DEFAULT_RUN_ID,
    source_match_key: str = DEFAULT_MATCH_KEY,
) -> Plan:
    item = PlanItem(
        row_id="row-1",
        line_no=1,
        op=op,
        target_id="target-1",
        desired_state=_base_desired_state(password=""),
        changes={},
        source_ref={"match_key": source_match_key},
        secret_fields=secret_fields,
    )
    return Plan(
        meta=PlanMeta(
            run_id=run_id,
            generated_at="now",
            dataset="employees",
            csv_path=None,
            plan_path=None,
            include_deleted=False,
        ),
        summary=PlanSummary(
            rows_total=1,
            valid_rows=1,
            failed_rows=0,
            planned_create=1 if op == Operation.CREATE else 0,
            planned_update=1 if op == Operation.UPDATE else 0,
            skipped=0,
        ),
        items=[item],
    )


def _set_master_key(monkeypatch: pytest.MonkeyPatch, *, key_version: str = "mk_2026") -> str:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"{key_version}:{key}")
    return key


def _write_vault_secret(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_id: str = DEFAULT_RUN_ID,
    secret_value: str = "TopSecret123",
) -> None:
    _set_master_key(monkeypatch)
    engine = open_sqlite(
        build_vault_db_config(SqliteSettings()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    try:
        store = SecretVaultWriteService(
            repository=SqliteVaultRepository(engine),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            locator=SecretLocatorService(),
        )
        store.put_many(
            dataset="employees",
            match_key=DEFAULT_MATCH_KEY,
            secrets={"password": secret_value},
            run_id=run_id,
        )
    finally:
        engine.close()


def _run_apply(
    *,
    tmp_path: Path,
    plan: Plan,
) -> tuple[ApplyResult, _DummyExecutor]:
    provider = build_secret_provider(
        "vault",
        paths_settings=_paths(tmp_path),
        run_id=plan.meta.run_id,
    )
    executor = _DummyExecutor()
    try:
        adapter = make_employees_spec(secrets=provider).get_apply_adapter()
        service = ImportApplyService(executor=executor)
        result = service.apply_plan(
            plan=plan,
            catalog=CATALOG,
            apply_adapter=adapter,
            stop_on_first_error=False,
            max_actions=None,
            max_item_outcomes=10,
        )
        return result, executor
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def test_apply_vault_hydrates_secret_and_executes_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_vault_secret(tmp_path=tmp_path, monkeypatch=monkeypatch, secret_value="VaultPassword")
    plan = _make_plan(op=Operation.CREATE, secret_fields=["password"])

    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert result.primary_code == SystemErrorCode.OK
    assert len(executor.calls) == 1
    assert isinstance(executor.calls[0].payload, dict)
    assert executor.calls[0].payload.get("password") == "VaultPassword"


@pytest.mark.parametrize("op", [Operation.CREATE, Operation.UPDATE])
def test_apply_vault_missing_required_secret_blocks_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    op: str,
):
    _set_master_key(monkeypatch)
    plan = _make_plan(op=op, secret_fields=["password"])

    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert result.primary_code == SystemErrorCode.DATA_INVALID
    assert len(executor.calls) == 0
    assert result.item_outcomes
    assert result.item_outcomes[0].diagnostics[0].code == "SECRET_REQUIRED"


def test_apply_vault_locator_drift_blocks_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_vault_secret(tmp_path=tmp_path, monkeypatch=monkeypatch)
    plan = _make_plan(
        op=Operation.CREATE,
        secret_fields=["password"],
        source_match_key="Doe|John|M|9999",
    )

    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert result.primary_code == SystemErrorCode.DATA_INVALID
    assert len(executor.calls) == 0
    assert result.item_outcomes
    assert result.item_outcomes[0].diagnostics[0].code == "SECRET_REQUIRED"


def test_apply_vault_read_error_blocks_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_vault_secret(tmp_path=tmp_path, monkeypatch=monkeypatch)
    vault_db_path = tmp_path / "cache" / "ankey_vault.sqlite3"
    conn = sqlite3.connect(str(vault_db_path))
    try:
        conn.execute(
            """
            UPDATE vault_secrets
            SET dek_version = 'missing_dek'
            WHERE dataset = 'employees' AND field = 'password'
            """
        )
        conn.commit()
    finally:
        conn.close()

    plan = _make_plan(op=Operation.CREATE, secret_fields=["password"])
    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert len(executor.calls) == 0
    assert result.item_outcomes
    assert result.item_outcomes[0].diagnostics[0].code == "SECRET_READ_ERROR"


def test_apply_vault_decryption_error_blocks_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_vault_secret(tmp_path=tmp_path, monkeypatch=monkeypatch)
    _set_master_key(monkeypatch, key_version="mk_2027")

    plan = _make_plan(op=Operation.CREATE, secret_fields=["password"])
    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert len(executor.calls) == 0
    assert result.item_outcomes
    assert result.item_outcomes[0].diagnostics[0].code == "SECRET_DECRYPTION_ERROR"


def test_apply_vault_integrity_error_blocks_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_vault_secret(tmp_path=tmp_path, monkeypatch=monkeypatch)
    vault_db_path = tmp_path / "cache" / "ankey_vault.sqlite3"
    conn = sqlite3.connect(str(vault_db_path))
    try:
        conn.execute(
            """
            UPDATE vault_secrets
            SET ciphertext = ?
            WHERE dataset = 'employees' AND field = 'password'
            """,
            (b"not-base64-token",),
        )
        conn.commit()
    finally:
        conn.close()

    plan = _make_plan(op=Operation.CREATE, secret_fields=["password"])
    result, executor = _run_apply(tmp_path=tmp_path, plan=plan)

    assert len(executor.calls) == 0
    assert result.item_outcomes
    assert result.item_outcomes[0].diagnostics[0].code == "SECRET_INTEGRITY_ERROR"
