"""
SQLite backend primitives for vault runtime.
"""

from connector.infra.secrets.sqlite.db import (
    DEFAULT_VAULT_DB_FILENAME,
    DEFAULT_VAULT_DB_PATH_ENV,
    VaultSqliteDb,
    getVaultDbPath,
    openVaultDb,
)
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import SCHEMA_VERSION, ensure_vault_schema

__all__ = [
    "DEFAULT_VAULT_DB_FILENAME",
    "DEFAULT_VAULT_DB_PATH_ENV",
    "SCHEMA_VERSION",
    "SqliteVaultRepository",
    "VaultSqliteDb",
    "ensure_vault_schema",
    "getVaultDbPath",
    "openVaultDb",
]
