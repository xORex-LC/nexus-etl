"""
SQLite backend primitives for vault runtime.
"""

from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import SCHEMA_VERSION, ensure_vault_schema

__all__ = [
    "SCHEMA_VERSION",
    "SqliteVaultRepository",
    "ensure_vault_schema",
]
