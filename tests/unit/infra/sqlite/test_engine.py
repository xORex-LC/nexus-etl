"""
Unit-тесты для connector/infra/sqlite/engine.py.

Проверяют: PRAGMA-профиль, transaction/autobegin/is_readonly/execute_with_retry.
Используют реальный SQLite (in-memory или tmp_path).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite


# ──────────────────────────────────────────────────────────────────────────────
# open_sqlite: PRAGMA и тип возврата
# ──────────────────────────────────────────────────────────────────────────────


def test_open_sqlite_returns_engine(tmp_path: Path) -> None:
    engine = open_sqlite(SqliteDbConfig(), str(tmp_path / "test.db"))
    try:
        assert isinstance(engine, SqliteEngine)
    finally:
        engine.close()


def test_open_sqlite_applies_pragma(tmp_path: Path) -> None:
    config = SqliteDbConfig(
        journal_mode="DELETE",
        synchronous="FULL",
        busy_timeout_ms=7777,
        foreign_keys=True,
        wal_autocheckpoint=500,
    )
    engine = open_sqlite(config, str(tmp_path / "test.db"))
    try:
        assert engine.fetchone("PRAGMA journal_mode")["journal_mode"].upper() == "DELETE"
        # synchronous: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
        assert int(engine.fetchone("PRAGMA synchronous")["synchronous"]) == 2
        assert int(engine.fetchone("PRAGMA busy_timeout")["timeout"]) == 7777
        assert int(engine.fetchone("PRAGMA foreign_keys")["foreign_keys"]) == 1
        assert int(engine.fetchone("PRAGMA wal_autocheckpoint")["wal_autocheckpoint"]) == 500
    finally:
        engine.close()


def test_open_sqlite_stores_db_path(tmp_path: Path) -> None:
    path = str(tmp_path / "test.db")
    engine = open_sqlite(SqliteDbConfig(), path)
    try:
        assert engine.db_path == path
    finally:
        engine.close()


# ──────────────────────────────────────────────────────────────────────────────
# transaction()
# ──────────────────────────────────────────────────────────────────────────────


def test_engine_transaction_default_mode() -> None:
    """transaction() без mode использует config.transaction_mode."""
    config = SqliteDbConfig(transaction_mode="immediate", journal_mode="DELETE")
    engine = open_sqlite(config, ":memory:")

    executed: list[str] = []
    engine.set_trace_callback(executed.append)

    engine.execute("CREATE TABLE t (id INTEGER)")
    with engine.transaction():
        engine.execute("INSERT INTO t VALUES (1)")

    engine.set_trace_callback(None)

    begin_stmts = [s.strip().upper() for s in executed if s.strip().upper().startswith("BEGIN")]
    assert len(begin_stmts) == 1
    assert begin_stmts[0] == "BEGIN IMMEDIATE"
    # Данные закоммичены
    assert engine.fetchone("SELECT COUNT(*) FROM t")[0] == 1


def test_engine_transaction_override_mode() -> None:
    """transaction(mode=...) переопределяет config.transaction_mode."""
    config = SqliteDbConfig(transaction_mode="deferred", journal_mode="DELETE")
    engine = open_sqlite(config, ":memory:")

    executed: list[str] = []
    engine.set_trace_callback(executed.append)

    engine.execute("CREATE TABLE t (id INTEGER)")
    with engine.transaction(mode="immediate"):  # override: deferred → immediate
        engine.execute("INSERT INTO t VALUES (1)")

    engine.set_trace_callback(None)

    begin_stmts = [s.strip().upper() for s in executed if s.strip().upper().startswith("BEGIN")]
    assert any("IMMEDIATE" in s for s in begin_stmts)


def test_engine_transaction_rollbacks_on_error() -> None:
    engine = open_sqlite(SqliteDbConfig(journal_mode="DELETE"), ":memory:")
    engine.execute("CREATE TABLE t (id INTEGER)")

    with pytest.raises(ValueError):
        with engine.transaction():
            engine.execute("INSERT INTO t VALUES (1)")
            raise ValueError("abort")

    assert engine.fetchone("SELECT COUNT(*) FROM t")[0] == 0


def test_engine_transaction_rejects_nested() -> None:
    engine = open_sqlite(SqliteDbConfig(journal_mode="DELETE"), ":memory:")
    engine.execute("CREATE TABLE t (id INTEGER)")

    with pytest.raises(RuntimeError, match="Nested transactions"):
        with engine.transaction():
            with engine.transaction():  # должно бросить
                pass


# ──────────────────────────────────────────────────────────────────────────────
# autobegin()
# ──────────────────────────────────────────────────────────────────────────────


def test_engine_autobegin_standalone() -> None:
    """autobegin() без активной транзакции открывает новую и коммитит."""
    engine = open_sqlite(SqliteDbConfig(journal_mode="DELETE"), ":memory:")
    engine.execute("CREATE TABLE t (id INTEGER, val TEXT)")

    with engine.autobegin():
        engine.execute("INSERT INTO t VALUES (1, 'a')")

    row = engine.fetchone("SELECT val FROM t WHERE id = 1")
    assert row["val"] == "a"


def test_engine_autobegin_join() -> None:
    """autobegin() внутри активной транзакции присоединяется без нового BEGIN."""
    engine = open_sqlite(SqliteDbConfig(journal_mode="DELETE"), ":memory:")
    engine.execute("CREATE TABLE t (id INTEGER, val TEXT)")

    executed: list[str] = []

    with engine.transaction():
        engine.execute("INSERT INTO t VALUES (1, 'outer')")
        engine.set_trace_callback(executed.append)  # начинаем трассировку
        with engine.autobegin():  # join: не должно выдать BEGIN
            engine.execute("INSERT INTO t VALUES (2, 'inner')")
        engine.set_trace_callback(None)

    begin_stmts = [s.strip().upper() for s in executed if s.strip().upper().startswith("BEGIN")]
    assert len(begin_stmts) == 0, "autobegin в активной транзакции не должен открывать новую BEGIN"

    rows = engine.fetchall("SELECT val FROM t ORDER BY id")
    assert len(rows) == 2
    assert rows[0]["val"] == "outer"
    assert rows[1]["val"] == "inner"


# ──────────────────────────────────────────────────────────────────────────────
# is_readonly()
# ──────────────────────────────────────────────────────────────────────────────


def test_engine_is_readonly_via_begin_immediate() -> None:
    """is_readonly() возвращает True когда SQLite сигнализирует о readonly-хранилище."""
    import unittest.mock as mock

    engine = open_sqlite(SqliteDbConfig(), ":memory:")

    def raise_readonly(sql: str, params=None):  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("attempt to write a readonly database")

    with mock.patch.object(engine, "execute", side_effect=raise_readonly):
        assert engine.is_readonly() is True


def test_engine_is_readonly_returns_false_for_writable(tmp_path: Path) -> None:
    engine = open_sqlite(SqliteDbConfig(journal_mode="DELETE"), str(tmp_path / "test.db"))
    try:
        assert engine.is_readonly() is False
    finally:
        engine.close()


def test_engine_is_readonly_propagates_other_errors() -> None:
    """is_readonly() пробрасывает OperationalError не связанные с readonly."""
    import unittest.mock as mock

    engine = open_sqlite(SqliteDbConfig(), ":memory:")

    def raise_io_error(sql: str, params=None):  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("disk I/O error")

    with mock.patch.object(engine, "execute", side_effect=raise_io_error):
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            engine.is_readonly()


# ──────────────────────────────────────────────────────────────────────────────
# execute_with_retry()
# ──────────────────────────────────────────────────────────────────────────────


def test_engine_execute_with_retry_schema() -> None:
    """execute_with_retry() повторяет вызов при SQLITE_SCHEMA и успешно завершает."""
    engine = open_sqlite(SqliteDbConfig(), ":memory:")
    engine.execute("CREATE TABLE t (id INTEGER)")

    call_count = 0
    original_execute = engine.execute

    def flaky_execute(sql: str, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Первый вызов — имитируем schema changed
            raise sqlite3.OperationalError("database schema has changed")
        return original_execute(sql, params)

    import unittest.mock as mock

    with mock.patch.object(engine, "execute", side_effect=flaky_execute):
        engine.execute_with_retry("SELECT 1", None, max_retries=1)

    assert call_count == 2  # одна неудача + одна успешная попытка


def test_engine_execute_with_retry_raises_after_exhaustion() -> None:
    """execute_with_retry() бросает после исчерпания попыток."""
    engine = open_sqlite(SqliteDbConfig(), ":memory:")

    def always_schema_error(sql: str, params=None):  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("database schema has changed")

    import unittest.mock as mock

    with mock.patch.object(engine, "execute", side_effect=always_schema_error):
        with pytest.raises(sqlite3.OperationalError, match="schema has changed"):
            engine.execute_with_retry("SELECT 1", None, max_retries=2)


def test_engine_execute_with_retry_non_schema_error_immediate_raise() -> None:
    """execute_with_retry() не делает retry для не-schema ошибок."""
    engine = open_sqlite(SqliteDbConfig(), ":memory:")
    call_count = 0

    def raise_locked(sql: str, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        raise sqlite3.OperationalError("database is locked")

    import unittest.mock as mock

    with mock.patch.object(engine, "execute", side_effect=raise_locked):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            engine.execute_with_retry("SELECT 1", None, max_retries=3)

    assert call_count == 1  # без retry
