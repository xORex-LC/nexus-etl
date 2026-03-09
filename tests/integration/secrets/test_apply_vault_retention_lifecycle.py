from __future__ import annotations

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from pathlib import Path

from cryptography.fernet import Fernet

from connector.datasets.registry import get_spec
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_models import Operation, Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.ports.target.execution import ExecutionResult, RequestExecutorProtocol, RequestSpec
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.secrets.vault_retention_service import VaultRetentionService
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.usecases.import_apply_service import ImportApplyService

CATALOG = build_catalog("employees", strict=True)


class _DummyExecutor(RequestExecutorProtocol):
    def __init__(self, *, ok: bool) -> None:
        self.ok = ok
        self.calls = 0

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        _ = spec
        self.calls += 1
        if self.ok:
            return ExecutionResult(ok=True, answer_code=200, response_payload={"_id": "id-1"})
        return ExecutionResult(ok=False, answer_code=500, error_message="boom")


def _vault_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "cache" / "ankey_vault.sqlite3")


def _base_state() -> dict[str, object]:
    return {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+1111111",
        "password": "",
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
    }


def _plan(*, lifecycle: dict[str, object] | None) -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="run-1",
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
            planned_create=1,
            planned_update=0,
            skipped=0,
        ),
        items=[
            PlanItem(
                row_id="row-1",
                line_no=1,
                op=Operation.CREATE,
                target_id="target-1",
                desired_state=_base_state(),
                changes={},
                source_ref={"match_key": "Doe|John|M|100"},
                secret_fields=["password"],
                secret_lifecycle=lifecycle,
            )
        ],
    )


def _write_secret(tmp_path: Path) -> None:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        _vault_db_path(tmp_path),
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
            match_key="Doe|John|M|100",
            secrets={"password": "TopSecret123"},
            run_id="run-1",
        )
    finally:
        engine.close()


def _read_secret_exists(tmp_path: Path) -> bool:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        _vault_db_path(tmp_path),
    )
    try:
        repo = SqliteVaultRepository(engine)
        locator_hash = SecretLocatorService().build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": "Doe|John|M|100"},
        )
        record = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash=locator_hash,
            locator_version="v1",
            run_id="run-1",
        )
        return record is not None
    finally:
        engine.close()


def _run_apply(tmp_path: Path, *, lifecycle: dict[str, object] | None, exec_ok: bool):
    db_path = _vault_db_path(tmp_path)
    engine = open_sqlite(to_vault_db_config(AppConfig()), db_path)
    try:
        repo = SqliteVaultRepository(engine)
        cipher = FernetEnvelopeCipher()
        key_provider = EnvVaultKeyProvider()
        locator = SecretLocatorService()
        provider = SecretVaultReadService(
            repository=repo,
            cipher=cipher,
            key_provider=key_provider,
            locator=locator,
            default_run_id="run-1",
        )
        retention = VaultRetentionService(repository=repo, locator=locator)
        adapter = get_spec("employees", secrets=provider).get_apply_adapter()
        result = ImportApplyService(
            executor=_DummyExecutor(ok=exec_ok),
            secret_retention=retention,
        ).apply_plan(
            plan=_plan(lifecycle=lifecycle),
            catalog=CATALOG,
            apply_adapter=adapter,
            stop_on_first_error=False,
            max_actions=None,
            max_item_outcomes=10,
        )
        return result
    finally:
        engine.close()


def test_apply_retention_persistent_keeps_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"mk_2026:{Fernet.generate_key().decode('utf-8')}")
    _write_secret(tmp_path)

    result = _run_apply(tmp_path, lifecycle={"mode": "persistent"}, exec_ok=True)

    assert result.primary_code == SystemErrorCode.OK
    assert _read_secret_exists(tmp_path) is True
    assert result.summary.retention_stats.get("kept") == 1


def test_apply_retention_ephemeral_deletes_on_success(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"mk_2026:{Fernet.generate_key().decode('utf-8')}")
    _write_secret(tmp_path)

    result = _run_apply(
        tmp_path,
        lifecycle={"mode": "ephemeral", "delete_on_success": True},
        exec_ok=True,
    )

    assert result.primary_code == SystemErrorCode.OK
    assert _read_secret_exists(tmp_path) is False
    assert result.summary.retention_stats.get("deleted") == 1


def test_apply_retention_ephemeral_keeps_secret_on_failed_apply(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"mk_2026:{Fernet.generate_key().decode('utf-8')}")
    _write_secret(tmp_path)

    result = _run_apply(
        tmp_path,
        lifecycle={"mode": "ephemeral", "delete_on_success": True},
        exec_ok=False,
    )

    assert result.primary_code != SystemErrorCode.OK
    assert _read_secret_exists(tmp_path) is True
    assert result.summary.retention_stats == {}
