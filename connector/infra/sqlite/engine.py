"""
Назначение:
    Единый SQLite-движок для всех баз данных проекта.
    Предоставляет SqliteEngine — обёртку над sqlite3.Connection —
    и фабричную функцию open_sqlite().

Граница ответственности:
    - Инкапсулирует sqlite3.Connection: наружу Connection не выходит.
    - Управляет транзакциями явно (isolation_level=None).
    - Предоставляет transaction(), autobegin(), is_readonly(), execute_with_retry().
    - Не знает о доменной логике, схемах таблиц и репозиториях.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from connector.infra.sqlite.config import SqliteDbConfig


def open_sqlite(config: SqliteDbConfig, path: str) -> "SqliteEngine":
    """
    Назначение:
        Единственная публичная точка входа для создания SQLite-соединения.
        Открывает/создаёт файл БД, применяет PRAGMA из config и возвращает SqliteEngine.

    Алгоритм:
        1. Создать родительские директории если путь не `:memory:`.
        2. Открыть соединение с isolation_level=None и row_factory=sqlite3.Row.
        3. Применить PRAGMA: foreign_keys, journal_mode, synchronous,
           busy_timeout, wal_autocheckpoint.
        4. Вернуть SqliteEngine(conn, config, path).

    Raises:
        sqlite3.OperationalError: если файл недоступен или PRAGMA не прошла.
    """
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row

    fk = "ON" if config.foreign_keys else "OFF"
    conn.execute(f"PRAGMA foreign_keys = {fk}")
    conn.execute(f"PRAGMA journal_mode = {config.journal_mode}")
    conn.execute(f"PRAGMA synchronous = {config.synchronous}")
    conn.execute(f"PRAGMA busy_timeout = {config.busy_timeout_ms}")
    conn.execute(f"PRAGMA wal_autocheckpoint = {config.wal_autocheckpoint}")

    return SqliteEngine(conn, config, path)


class SqliteEngine:
    """
    Назначение:
        Тонкая обёртка над sqlite3.Connection с единым API для SQL-операций,
        явным управлением транзакциями и встроенными утилитами (is_readonly, retry).

    Инварианты:
        - Соединение открыто с isolation_level=None: транзакции только явные.
        - conn.in_transaction достаточно для проверки активной транзакции;
          _transaction_depth-счётчик не нужен.
        - sqlite3.Connection не экспортируется наружу; доступен только через методы движка.
        - db_path хранит путь, переданный в open_sqlite (для диагностики/логирования).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: SqliteDbConfig,
        db_path: str,
    ) -> None:
        self._conn = conn
        self._config = config
        self.db_path = db_path

    # ──────────────────────────────────────────────
    # Базовый SQL API
    # ──────────────────────────────────────────────

    def execute(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def executemany(
        self, sql: str, seq_of_params: list[tuple] | list[dict]
    ) -> sqlite3.Cursor:
        return self._conn.executemany(sql, seq_of_params)

    def fetchone(
        self, sql: str, params: tuple | dict | None = None
    ) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def fetchall(
        self, sql: str, params: tuple | dict | None = None
    ) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    # ──────────────────────────────────────────────
    # Управление транзакциями
    # ──────────────────────────────────────────────

    @contextmanager
    def transaction(self, mode: str | None = None) -> Iterator[None]:
        """
        Назначение:
            Открыть явную транзакцию с нужным mode и гарантировать COMMIT/ROLLBACK.

        Алгоритм:
            1. Проверить, что соединение не в транзакции (вложенные не поддерживаются).
            2. Вычислить effective_mode: mode or config.transaction_mode.
            3. Выполнить BEGIN <MODE>.
            4. yield — тело транзакции.
            5. COMMIT при успехе, ROLLBACK при исключении.

        Raises:
            RuntimeError: если соединение уже в транзакции (nested).
            sqlite3.OperationalError: пробрасывается при ошибке BEGIN/COMMIT/ROLLBACK.
        """
        if self._conn.in_transaction:
            raise RuntimeError("Nested transactions are not supported")

        effective_mode = (mode or self._config.transaction_mode).upper()
        self._conn.execute(f"BEGIN {effective_mode}")
        try:
            yield
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    @contextmanager
    def autobegin(self, mode: str | None = None) -> Iterator[None]:
        """
        Назначение:
            «Мягкий» вариант transaction(): присоединиться к активной транзакции
            или начать новую. Используется в репозиториях вместо _write_unit()-паттерна.

        Алгоритм:
            - Если conn.in_transaction → yield (join активной tx без нового BEGIN/COMMIT).
            - Иначе → with self.transaction(mode): yield.

        Важно:
            При join активной транзакции exceptions не перехватываются и не вызывают ROLLBACK —
            внешняя транзакция решает судьбу изменений.
        """
        if self._conn.in_transaction:
            yield
            return
        with self.transaction(mode=mode):
            yield

    # ──────────────────────────────────────────────
    # Утилиты
    # ──────────────────────────────────────────────

    def is_readonly(self) -> bool:
        """
        Назначение:
            Определить, доступна ли БД для записи, включая filesystem-уровень.

        Алгоритм:
            1. Попытаться BEGIN IMMEDIATE (требует write-lock).
            2. Успех → ROLLBACK, return False.
            3. OperationalError с «readonly» в тексте → return True.
            4. Иные OperationalError → пробросить (не маскировать неожиданные ошибки).

        Важно:
            Метод предназначен для вызова до начала рабочих транзакций (startup).
            Проверка через BEGIN IMMEDIATE выявляет реальную write-capability,
            включая read-only filesystem — в отличие от sqlite_master-запросов.

        Raises:
            sqlite3.OperationalError: если ошибка не связана с readonly-статусом.
        """
        try:
            self.execute("BEGIN IMMEDIATE")
            self.execute("ROLLBACK")
            return False
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                return True
            raise

    def execute_with_retry(
        self,
        sql: str,
        params: tuple | dict | None,
        max_retries: int,
    ) -> sqlite3.Cursor:
        """
        Назначение:
            Выполнить SQL с автоматическим retry при SQLITE_SCHEMA.

        Алгоритм:
            1. Попытаться execute(sql, params).
            2. При OperationalError: если _is_schema_changed → retry (до max_retries раз).
            3. При иной ошибке или исчерпании попыток — пробросить.

        Raises:
            sqlite3.OperationalError: при non-schema ошибке или исчерпании retry.
        """
        for attempt in range(max_retries + 1):
            try:
                return self.execute(sql, params)
            except sqlite3.OperationalError as exc:
                if _is_schema_changed(exc) and attempt < max_retries:
                    continue
                raise

        # Защитный блок: цикл всегда завершается через return или raise выше.
        raise RuntimeError("Unreachable execute_with_retry state")  # pragma: no cover

    def close(self) -> None:
        """Освободить sqlite3.Connection. Вызывается при teardown Singleton-провайдера."""
        self._conn.close()

    def set_trace_callback(self, fn: Callable[[str], None] | None) -> None:
        """
        Назначение:
            Зарегистрировать callback для трассировки всех SQL-выражений.
            Используется для диагностики и в тестах (верификация BEGIN-statement).
        """
        self._conn.set_trace_callback(fn)


def _is_schema_changed(exc: sqlite3.DatabaseError) -> bool:
    """True если исключение соответствует SQLITE_SCHEMA (схема изменилась)."""
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code == sqlite3.SQLITE_SCHEMA:
        return True
    return "schema has changed" in str(exc).lower()
