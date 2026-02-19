from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.secrets.vault_retention_service import VaultRetentionService
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository, VaultSqliteDb


def _new_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _build_repo(tmp_path: Path) -> tuple[SqliteVaultRepository, VaultSqliteDb]:
    db = VaultSqliteDb(db_path=str(tmp_path / "cache" / "ankey_vault.sqlite3"))
    return SqliteVaultRepository(db), db


def _write_secret(repo: SqliteVaultRepository, *, value: str = "TopSecret123", run_id: str = "run-1") -> None:
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{_new_key()}"})
    store = SecretVaultWriteService(
        repository=repo,
        cipher=FernetEnvelopeCipher(),
        key_provider=key_provider,
        locator=SecretLocatorService(),
    )
    store.put_many(
        dataset="employees",
        match_key="Doe|John|M|100",
        secrets={"password": value},
        run_id=run_id,
    )


def test_retention_persistent_keeps_secret(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    locator = SecretLocatorService()
    try:
        _write_secret(repo, run_id="run-1")
        service = VaultRetentionService(repository=repo, locator=locator)

        counters = service.on_apply_success(
            dataset="employees",
            op="create",
            source_ref={"match_key": "Doe|John|M|100"},
            secret_fields=["password"],
            secret_lifecycle={"mode": "persistent", "delete_on_success": False},
            run_id="run-1",
        )

        locator_hash = locator.build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": "Doe|John|M|100"},
        )
        assert repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash=locator_hash,
            locator_version="v1",
            run_id="run-1",
        ) is not None
        assert counters["deleted"] == 0
        assert counters["kept"] == 1
    finally:
        db.close()


def test_retention_ephemeral_deletes_secret_on_success(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    locator = SecretLocatorService()
    try:
        _write_secret(repo, run_id="run-1")
        service = VaultRetentionService(repository=repo, locator=locator)

        counters = service.on_apply_success(
            dataset="employees",
            op="update",
            source_ref={"match_key": "Doe|John|M|100"},
            secret_fields=["password"],
            secret_lifecycle={"mode": "ephemeral", "delete_on_success": True},
            run_id="run-1",
        )

        locator_hash = locator.build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": "Doe|John|M|100"},
        )
        assert repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash=locator_hash,
            locator_version="v1",
            run_id="run-1",
        ) is None
        assert counters["deleted"] == 1
        assert counters["errors"] == 0
    finally:
        db.close()


def test_retention_ephemeral_skips_delete_when_source_ref_is_missing(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    try:
        _write_secret(repo, run_id="run-1")
        service = VaultRetentionService(repository=repo, locator=SecretLocatorService())

        counters = service.on_apply_success(
            dataset="employees",
            op="create",
            source_ref=None,
            secret_fields=["password"],
            secret_lifecycle={"mode": "ephemeral"},
            run_id="run-1",
        )

        assert counters["deleted"] == 0
        assert counters["skipped"] == 1
    finally:
        db.close()


def test_retention_maintenance_hooks_are_available(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    try:
        service = VaultRetentionService(repository=repo, locator=SecretLocatorService())
        maintenance = service.run_maintenance()
        assert maintenance == {
            "cleanup_expired": 0,
            "cleanup_orphans": 0,
            "rewrap_candidates": 0,
        }
    finally:
        db.close()

