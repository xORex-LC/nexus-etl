"""
Pyperf benchmark for vault-management lifecycle operations.

The benchmark exercises the current unseal runtime model end-to-end:
SQLite schema, unseal metadata, Argon2id key derivation, startup probe,
DEK wrap/rewrap and encrypted secret rows.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pyperf

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.infra.secrets import FernetEnvelopeCipher, UnsealedVaultKeyProvider, VaultUnsealService
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite
from connector.usecases.management.vault import VaultKeyManagementUseCase, VaultStartupGuardPostVerifier

FAST_MODE = "--fast" in sys.argv or "--debug-single-value" in sys.argv
SECRETS_PER_DB = 3 if FAST_MODE else 25
PASSPHRASE = "vault-management-pyperf-passphrase"
NEW_PASSPHRASE = "vault-management-pyperf-new-passphrase"


def _sqlite_config() -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode="immediate",
        busy_timeout_ms=5000,
        journal_mode="WAL",
        synchronous="NORMAL",
        foreign_keys=True,
        wal_autocheckpoint=1000,
        schema_retry_count=2,
    )


def _build_context(db_path: Path) -> tuple[
    object,
    SqliteVaultRepository,
    FernetEnvelopeCipher,
    VaultUnsealService,
    VaultKeyManagementUseCase,
]:
    engine = open_sqlite(_sqlite_config(), str(db_path))
    repository = SqliteVaultRepository(engine)
    cipher = FernetEnvelopeCipher()
    unseal_service = VaultUnsealService()
    post_verify = VaultStartupGuardPostVerifier(
        repository=repository,
        cipher=cipher,
        storage_probe=engine,
    )
    usecase = VaultKeyManagementUseCase(
        repository=repository,
        cipher=cipher,
        unseal_service=unseal_service,
        post_verify=post_verify,
    )
    return engine, repository, cipher, unseal_service, usecase


def _seed_vault(db_path: Path, *, passphrase: str = PASSPHRASE) -> tuple[object, VaultKeyManagementUseCase]:
    engine, repository, cipher, unseal_service, usecase = _build_context(db_path)
    usecase.init_keyring(passphrase=passphrase, run_id="bench-init")

    key_provider = UnsealedVaultKeyProvider(
        repository=repository,
        unseal_service=unseal_service,
        passphrase=passphrase,
    )
    writer = SecretVaultWriteService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=SecretLocatorService(),
    )
    for index in range(SECRETS_PER_DB):
        writer.put_many(
            dataset="employees",
            match_key=f"employee-{index}",
            secrets={"password": f"secret-{index}"},
            run_id="bench",
        )
    return engine, usecase


def bench_management_init(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        with tempfile.TemporaryDirectory(prefix="ankey-vault-init-") as tmp:
            engine, _repository, _cipher, _unseal_service, usecase = _build_context(Path(tmp) / "vault.sqlite3")
            t0 = timer()
            result = usecase.init_keyring(passphrase=PASSPHRASE, run_id="bench-init")
            total += timer() - t0
            assert result.operation == "init"
            engine.close()
    return total


def bench_management_status_verify(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        with tempfile.TemporaryDirectory(prefix="ankey-vault-status-") as tmp:
            engine, usecase = _seed_vault(Path(tmp) / "vault.sqlite3")
            t0 = timer()
            active_key = usecase.verify_unseal(passphrase=PASSPHRASE)
            total += timer() - t0
            assert active_key.is_active
            engine.close()
    return total


def bench_management_rotate(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        with tempfile.TemporaryDirectory(prefix="ankey-vault-rotate-") as tmp:
            engine, usecase = _seed_vault(Path(tmp) / "vault.sqlite3")
            t0 = timer()
            result = usecase.rotate_and_rewrap(
                current_passphrase=PASSPHRASE,
                new_passphrase=NEW_PASSPHRASE,
                run_id="bench-rotate",
            )
            total += timer() - t0
            assert result.operation == "rotate"
            assert result.dek_rewrapped_count >= 1
            engine.close()
    return total


def bench_management_rewrap(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        with tempfile.TemporaryDirectory(prefix="ankey-vault-rewrap-") as tmp:
            engine, usecase = _seed_vault(Path(tmp) / "vault.sqlite3")
            t0 = timer()
            result = usecase.rewrap_all_dek(passphrase=PASSPHRASE, run_id="bench-rewrap")
            total += timer() - t0
            assert result.operation == "rewrap"
            assert result.dek_rewrapped_count >= 1
            engine.close()
    return total


if __name__ == "__main__":
    runner = pyperf.Runner(processes=1, min_time=0.001 if FAST_MODE else 0.1, warmups=0 if FAST_MODE else 1)
    runner.metadata["description"] = "Vault unseal runtime management lifecycle benchmark"
    runner.bench_time_func("vault_management_init", bench_management_init)
    runner.bench_time_func("vault_management_status_verify", bench_management_status_verify)
    runner.bench_time_func("vault_management_rotate_rewrap", bench_management_rotate)
    runner.bench_time_func("vault_management_rewrap", bench_management_rewrap)
