"""Контракты событий наблюдаемости — нейтральные к runtime намерения логирования.

Модуль определяет небольшие value objects, через которые сценарии, delivery-оркестрация
и инфраструктурные адаптеры описывают произошедшее событие без привязки к ECS JSON-полям
или конкретному backend логирования.

Границы ответственности:
    - Определять канонический объект намерения для observability logging.
    - Определять стабильные enum-значения для зональных адаптеров и sink-ов событий.
    - Держать runtime-контракты импортируемыми из любого слоя приложения.

Вне ответственности:
    - Рендеринг ECS JSON-полей.
    - Вызов structlog или управление log handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, TypeAlias


LogScalarValue: TypeAlias = str | int | float | bool | None
LogFieldValue: TypeAlias = LogScalarValue | tuple[LogScalarValue, ...]


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


class EventKind(StrEnum):
    EVENT = "event"
    METRIC = "metric"
    STATE = "state"


@dataclass(frozen=True)
class ObservabilityError:
    """Безопасное описание ошибки внутри observability-события."""

    type: str
    message: str
    code: str | None = None


@dataclass(frozen=True)
class ObservabilityEvent:
    """Описать одно наблюдаемое событие приложения до ECS-рендеринга.

    `fields` — короткие доменные алиасы. Это намеренно не dotted ECS keys:
    renderer владеет маппингом alias-to-ECS и fallback-политикой `labels.*`.
    """

    action: str
    message: str
    fields: Mapping[str, LogFieldValue] = field(default_factory=dict)
    level: LogLevel | None = None
    outcome: EventOutcome | None = None
    kind: EventKind | None = None
    duration_ns: int | None = None
    error: ObservabilityError | None = None


__all__ = [
    "EventKind",
    "EventOutcome",
    "LogFieldValue",
    "LogLevel",
    "LogScalarValue",
    "ObservabilityError",
    "ObservabilityEvent",
]
