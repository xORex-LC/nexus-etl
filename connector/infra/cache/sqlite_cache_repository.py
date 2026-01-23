from __future__ import annotations

import sqlite3
from typing import Any

from connector.domain.ports.cache_repo import CacheRepositoryProtocol
from connector.infra.cache.db import ensureSchema
from connector.infra.cache.repo import (
    clearOrgs,
    clearUsers,
    getCounts,
    getMetaValue,
    setMetaValue,
    upsertOrganization,
    upsertUser,
)


class SqliteCacheRepository(CacheRepositoryProtocol):
    """
    Назначение/ответственность:
        Адаптер репозитория кэша на SQLite.
    Взаимодействия:
        Использует существующие функции infra/cache/repo.py.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        ensureSchema(self.conn)

    def begin(self) -> None:
        self.conn.execute("BEGIN")

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def upsert_user(self, user_row: dict[str, Any]) -> str:
        return upsertUser(self.conn, user_row)

    def upsert_org(self, org_row: dict[str, Any]) -> str:
        return upsertOrganization(self.conn, org_row)

    def clear_users(self) -> int:
        return clearUsers(self.conn)

    def clear_orgs(self) -> int:
        return clearOrgs(self.conn)

    def get_counts(self) -> tuple[int, int]:
        return getCounts(self.conn)

    def get_meta(self, key: str) -> str | None:
        return getMetaValue(self.conn, key)

    def set_meta(self, key: str, value: str | None) -> None:
        setMetaValue(self.conn, key, value)
