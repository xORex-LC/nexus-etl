"""
Назначение:
    Модели результата apply use-case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from connector.domain.models import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.record_ref import RecordRef


@dataclass(frozen=True)
class ApplySummary:
    created: int
    updated: int
    failed: int
    skipped: int

    items_total: int
    rows_with_warnings: int

    error_stats: Mapping[str, int]


@dataclass(frozen=True)
class ApplyItemOutcome:
    record_ref: RecordRef
    op: str  # операция из PlanItem: 'create' | 'update'
    status: str  # итог item: 'OK' | 'FAILED'
    target_id: str | None
    diagnostics: Tuple[DiagnosticItem, ...]


@dataclass(frozen=True)
class ApplyResult:
    summary: ApplySummary

    primary_code: SystemErrorCode
    all_codes: Tuple[SystemErrorCode, ...]
    fatal_error: bool

    item_outcomes: Tuple[ApplyItemOutcome, ...]
    outcomes_truncated: bool
