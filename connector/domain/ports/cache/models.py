"""
Назначение:
    Общие модели cache boundary (DTO и enum), не зависящие от конкретного хранилища.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UpsertResult(str, Enum):
    """
    Назначение:
        Результат операции upsert в кэше.
    """

    INSERTED = "inserted"
    UPDATED = "updated"


@dataclass(frozen=True)
class FieldSpec:
    """
    Назначение:
        Компилированное описание поля cache snapshot таблицы.
    """

    name: str
    type: str
    nullable: bool = True
    source: str | None = None


@dataclass(frozen=True)
class CacheSpec:
    """
    Назначение:
        Компилированная схема cache snapshot таблицы датасета.
    """

    dataset: str
    table: str
    primary_key: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    unique_indexes: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class CacheMeta:
    """
    Назначение:
        Контейнер метаданных кэша.
    """

    values: dict[str, str | None]


class PendingStatus(str, Enum):
    """
    Назначение:
        Состояние pending-ссылки.
    """

    PENDING = "pending"
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PendingLink:
    """
    Назначение:
        DTO для pending-ссылок.
    """

    pending_id: int
    dataset: str
    source_row_id: str
    field: str
    lookup_key: str
    status: str
    attempts: int
    created_at: str | None
    last_attempt_at: str | None
    expires_at: str | None
    reason: str | None
    payload: str | None


@dataclass(frozen=True)
class PendingRow:
    """
    Назначение:
        Снимок строки для re-resolve.
    """

    dataset: str
    source_row_id: str
    payload: str
