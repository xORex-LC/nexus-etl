from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator


class SqliteEngine:
    """
    Назначение/ответственность:
        Тонкая обёртка над sqlite3.Connection с единым API для SQL-операций.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def execute(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        if params is None:
            return self.conn.execute(sql)
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: list[tuple] | list[dict]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, seq_of_params)

    def fetchone(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Row | None:
        cur = self.execute(sql, params)
        return cur.fetchone()

    def fetchall(self, sql: str, params: tuple | dict | None = None) -> list[sqlite3.Row]:
        cur = self.execute(sql, params)
        return cur.fetchall()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN")
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
