from __future__ import annotations

from pathlib import Path

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.unseal import VaultUnsealService
from connector.infra.sqlite.engine import open_sqlite


def test_sqlite_repository_persists_unseal_metadata(tmp_path: Path) -> None:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    try:
        repo = SqliteVaultRepository(engine)
        metadata, _ = VaultUnsealService().create_metadata(
            passphrase="correct horse battery",
            key_version="mk_2026",
            now_utc="2026-04-28T00:00:00+00:00",
        )

        repo.upsert_unseal_metadata(metadata)
        loaded = repo.get_unseal_metadata()

        assert loaded == metadata
    finally:
        engine.close()
