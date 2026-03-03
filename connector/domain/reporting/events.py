"""
Назначение:
    Доменные события report-layer для event-driven ingestion (DEC-001).

Граница ответственности:
    - Содержит только immutable DTO-события.
    - Не хранит состояние отчёта и не выполняет агрегацию.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from connector.domain.models import RowRef
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, ReportOpKey
from connector.domain.reporting.models import ReportDiagnostic


@dataclass(frozen=True)
class ReportEvent:
    """
    Назначение:
        Базовый маркер события report-layer.
    """


@dataclass(frozen=True)
class SetMetaEvent(ReportEvent):
    """
    Назначение:
        Обновление метаданных запуска.
    """

    dataset: str | None = None
    items_limit: int | None = None
    app_version: str | None = None
    git_rev: str | None = None


@dataclass(frozen=True)
class SetContextEvent(ReportEvent):
    """
    Назначение:
        Установка namespaced context block.
    """

    name: ReportContextKey | str
    value: dict[str, Any]


@dataclass(frozen=True)
class AddOpEvent(ReportEvent):
    """
    Назначение:
        Инкремент стандартных op-счётчиков.
    """

    name: ReportOpKey | str
    ok: int = 0
    failed: int = 0
    count: int = 0


@dataclass(frozen=True)
class MergeOpFieldsEvent(ReportEvent):
    """
    Назначение:
        Merge произвольных полей в summary.ops[name].
    """

    name: ReportOpKey | str
    values: Mapping[str, int]


@dataclass(frozen=True)
class SetRowCountersEvent(ReportEvent):
    """
    Назначение:
        Compatibility bridge для pre-aggregated row counters.
    """

    rows_total: int
    rows_passed: int
    rows_blocked: int
    rows_with_warnings: int
    rows_skipped: int = 0


@dataclass(frozen=True)
class AddItemEvent(ReportEvent):
    """
    Назначение:
        Добавление row-level item и связанных diagnostic данных.
    """

    status: ReportItemStatus | str
    row_ref: RowRef | None = None
    payload: Mapping[str, Any] | None = None
    errors: tuple[ReportDiagnostic, ...] = field(default_factory=tuple)
    warnings: tuple[ReportDiagnostic, ...] = field(default_factory=tuple)
    meta: dict[str, Any] = field(default_factory=dict)
    store: bool = True
    preaggregated: bool = False


@dataclass(frozen=True)
class SetItemsTruncatedEvent(ReportEvent):
    """
    Назначение:
        Явная фиксация флага items_truncated.
    """

    value: bool = True


@dataclass(frozen=True)
class EnsureErrorsTotalAtLeastEvent(ReportEvent):
    """
    Назначение:
        Зафиксировать минимальное значение summary.errors_total.
    """

    value: int


@dataclass(frozen=True)
class SetStatusEvent(ReportEvent):
    """
    Назначение:
        Явно задать итоговый статус отчёта.
    """

    status: str | None


@dataclass(frozen=True)
class FinishEvent(ReportEvent):
    """
    Назначение:
        Финализация отчёта (timestamps + duration).
    """

    finished_at: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class ActivityMetricEvent(ReportEvent):
    """
    Назначение:
        Фасад-событие для подсистемных метрик через IActivitySink.
    """

    name: str
    payload: Mapping[str, Any]
