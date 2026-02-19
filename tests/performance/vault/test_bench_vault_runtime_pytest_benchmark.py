"""Benchmark-тесты vault runtime через pytest-benchmark."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite


pytestmark = pytest.mark.performance


def test_benchmark_vault_put_and_get(benchmark, tmp_path: Path) -> None:
    master_key = Fernet.generate_key().decode("utf-8")
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}"})
    cipher = FernetEnvelopeCipher()
    locator = SecretLocatorService()

    db_path = tmp_path / "vault_bench.sqlite3"
    engine = open_sqlite(
        SqliteDbConfig(
            transaction_mode="immediate",
            busy_timeout_ms=5000,
            journal_mode="WAL",
            synchronous="NORMAL",
        ),
        str(db_path),
    )
    repository = SqliteVaultRepository(engine)
    writer = SecretVaultWriteService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )
    reader = SecretVaultReadService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
        default_run_id="bench",
    )
    seq = [0]

    def _op_cycle() -> None:
        idx = seq[0]
        seq[0] = idx + 1
        match_key = f"bench-key-{idx}"
        writer.put_many(
            dataset="employees",
            match_key=match_key,
            secrets={"password": f"pw-{idx}"},
            run_id="bench",
        )
        value = reader.get_secret(
            dataset="employees",
            field="password",
            source_ref={"match_key": match_key},
            run_id="bench",
        )
        assert value == f"pw-{idx}"

    try:
        benchmark(_op_cycle)
    finally:
        engine.close()
