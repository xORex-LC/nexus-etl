from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from connector.domain.models import DiagnosticStage, RowRef


@dataclass
class ReportMeta:
    """
    Назначение:
        Универсальные метаданные запуска команды.
    """

    run_id: str
    dataset: str | None
    command: str
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = None
    items_limit: int | None = None
    items_truncated: bool = False
    app_version: str | None = None
    git_rev: str | None = None


@dataclass
class ReportSummary:
    """
    Назначение:
        Унифицированные счётчики выполнения.
    """

    rows_total: int = 0
    rows_passed: int = 0
    rows_blocked: int = 0
    rows_with_warnings: int = 0
    errors_total: int = 0
    warnings_total: int = 0
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)
    ops: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportDiagnostic:
    """
    Назначение:
        Диагностика по конкретной записи.
    """

    severity: str
    stage: DiagnosticStage
    code: str
    field: str | None
    message: str
    rule: str | None = None


@dataclass
class ReportItem:
    """
    Назначение:
        Единица отчёта, привязанная к конкретной записи.
    """

    status: str
    row_ref: RowRef | None = None
    payload: Mapping[str, Any] | None = None
    diagnostics: list[ReportDiagnostic] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportEnvelope:
    """
    Назначение:
        Корневой объект отчёта.
    """

    status: str
    meta: ReportMeta
    summary: ReportSummary
    items: list[ReportItem]
    context: dict[str, Any] = field(default_factory=dict)

