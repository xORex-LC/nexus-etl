from __future__ import annotations

from pathlib import Path

from connector.config.loader import load_app_config
from connector.config.projections import to_vault_db_config
from connector.infra.secrets import FernetEnvelopeCipher, VaultUnsealService
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import ensure_vault_schema
from connector.infra.sqlite.engine import open_sqlite
from connector.usecases.management.vault import (
    VaultKeyManagementUseCase,
    VaultStartupGuardPostVerifier,
)

TEST_UNSEAL_PASSPHRASE = "Test-Unseal-Passphrase-2026"


def initialize_test_vault(cache_dir: Path, passphrase: str = TEST_UNSEAL_PASSPHRASE) -> None:
    """Create unseal metadata and startup probe for CLI/integration tests."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    engine = open_sqlite(
        to_vault_db_config(load_app_config().app_config),
        str(cache_dir / "ankey_vault.sqlite3"),
    )
    try:
        ensure_vault_schema(engine)
        repository = SqliteVaultRepository(engine)
        cipher = FernetEnvelopeCipher()
        usecase = VaultKeyManagementUseCase(
            repository=repository,
            cipher=cipher,
            unseal_service=VaultUnsealService(),
            post_verify=VaultStartupGuardPostVerifier(
                repository=repository,
                cipher=cipher,
                storage_probe=engine,
            ),
        )
        if not usecase.status().initialized:
            usecase.init_keyring(passphrase=passphrase)
    finally:
        engine.close()
