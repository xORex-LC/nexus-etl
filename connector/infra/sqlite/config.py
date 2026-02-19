"""
Назначение:
    Иммутабельная конфигурация одного SQLite-соединения.
    Используется фабричной функцией open_sqlite() для применения PRAGMA
    и выбора transaction mode.

Граница ответственности:
    - Хранит параметры соединения: transaction mode, таймауты, PRAGMA-настройки.
    - Не знает о путях к файлам, lifecycle и DI-контейнере.
    - Не управляет самим соединением.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SqliteDbConfig:
    """
    Назначение:
        Иммутабельный набор параметров для одного SQLite-соединения.

    Инварианты:
        - Все поля — значения по умолчанию, пригодные для production (WAL, NORMAL, 5s timeout).
        - schema_retry_count=0 означает «без retry»; >0 включает retry при SQLITE_SCHEMA.
        - Экземпляр frozen: изменение конфига требует создания нового объекта.
    """

    transaction_mode: Literal["deferred", "immediate", "exclusive"] = "deferred"
    busy_timeout_ms: int = 5000
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    foreign_keys: bool = True
    wal_autocheckpoint: int = 1000
    schema_retry_count: int = 0  # >0 включает retry при SQLITE_SCHEMA
