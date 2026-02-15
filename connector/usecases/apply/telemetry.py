"""
Назначение:
    Порт телеметрии apply use-case и no-op реализация.
"""

from __future__ import annotations

from typing import Protocol

from connector.domain.models import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.record_ref import RecordRef
from connector.usecases.apply.models import ApplySummary


class ApplyTelemetrySink(Protocol):
    """Выходной порт событий apply (per-item и итоговый summary)."""

    def on_item_ok(self, *, record_ref: RecordRef, op: str, target_id: str | None) -> None: ...
    def on_item_warn(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None: ...
    def on_item_error(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None: ...

    def on_summary(
        self,
        *,
        primary_code: SystemErrorCode,
        all_codes: tuple[SystemErrorCode, ...],
        fatal_error: bool,
        counters: ApplySummary,
    ) -> None: ...


class NullApplyTelemetrySink:
    """Пустая реализация порта телеметрии (паттерн Null Object)."""

    def on_item_ok(self, *, record_ref: RecordRef, op: str, target_id: str | None) -> None:
        pass

    def on_item_warn(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None:
        pass

    def on_item_error(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None:
        pass

    def on_summary(
        self,
        *,
        primary_code: SystemErrorCode,
        all_codes: tuple[SystemErrorCode, ...],
        fatal_error: bool,
        counters: ApplySummary,
    ) -> None:
        pass
