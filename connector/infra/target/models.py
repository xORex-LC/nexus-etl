"""
Typed boundary models для target-slice.

Назначение:
    Иммутабельные модели для взаимодействия с target-системой.
    Используются на границе runtime ↔ delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.domain.diagnostics.policies import SystemErrorCode

TargetFaultKind = Literal[
    "SPEC",
    "AUTH",
    "PERMISSION",
    "DATA",
    "NOT_FOUND",
    "CONFLICT",
    "THROTTLE",
    "TRANSIENT",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class TargetMeta:
    """Метаданные target-системы."""

    target_type: str
    base_url: str | None = None
    transport: str = "http"


@dataclass(frozen=True, slots=True)
class TargetStats:
    """Статистика взаимодействия с target."""

    requests_total: int = 0
    retries_total: int = 0
    failures_total: int = 0


@dataclass(frozen=True, slots=True)
class TargetCheckResult:
    """Результат health-check target-системы."""

    ok: bool
    latency_ms: int | None = None
    fault_kind: TargetFaultKind | None = None
    error_code: SystemErrorCode | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class TargetConnectionConfig:
    """Конфигурация подключения к target."""

    target_type: str
    base_url: str
    username: str
    transport: str = "http"
