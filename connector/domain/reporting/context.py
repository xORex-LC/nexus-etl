"""
Назначение:
    In-memory execution context для event-driven report ingestion (DEC-001).

Граница ответственности:
    - Агрегирует события потоково (streaming counters).
    - Хранит только bounded sample row-items согласно items_limit.
    - Не рендерит артефакты и не управляет runtime lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from connector.common.time import get_now_iso
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.contracts import (
    normalize_context_key,
    normalize_item_status,
    normalize_op_key,
    ReportContextKey,
    ReportItemStatus,
)
from connector.domain.reporting.events import (
    ActivityMetricEvent,
    AddItemEvent,
    AddOpEvent,
    EnsureErrorsTotalAtLeastEvent,
    FinishEvent,
    MergeOpFieldsEvent,
    ReportEvent,
    SetContextEvent,
    SetItemsTruncatedEvent,
    SetMetaEvent,
    SetRowCountersEvent,
    SetStatusEvent,
)
from connector.domain.reporting.models import (
    ReportEnvelope,
    ReportItem,
    ReportMeta,
    ReportSummary,
)


@runtime_checkable
class IReportContext(Protocol):
    """
    Назначение:
        Контракт event-driven контекста отчёта на время одной команды.
    """

    def append(self, event: ReportEvent) -> None: ...

    def snapshot(self) -> ReportEnvelope: ...

    def meta_snapshot(self) -> ReportMeta: ...

    def summary_snapshot(self) -> ReportSummary: ...

    def items_snapshot(self) -> list[ReportItem]: ...

    def context_snapshot(self) -> dict[str, Any]: ...

    def status_snapshot(self) -> str | None: ...


class InMemoryReportContext(IReportContext):
    """
    Назначение:
        Command-scoped in-memory контекст отчёта.

    Контракт:
        - Сохраняет только агрегаты + bounded items sample.
        - Не держит сырые row-события (bounded memory стратегия DEC-001).
    """

    def __init__(
        self,
        *,
        run_id: str,
        command: str,
        started_at: str | None = None,
    ) -> None:
        self._meta = ReportMeta(
            run_id=run_id,
            dataset=None,
            command=command,
            started_at=started_at or get_now_iso(),
        )
        self._summary = ReportSummary()
        self._items: list[ReportItem] = []
        self._context: dict[str, Any] = {}
        self._status: str | None = None

    def append(self, event: ReportEvent) -> None:
        """
        Назначение:
            Применить событие к текущему состоянию контекста.
        """
        if isinstance(event, SetMetaEvent):
            if event.dataset is not None:
                self._meta.dataset = event.dataset
            if event.items_limit is not None:
                self._meta.items_limit = int(event.items_limit)
            if event.app_version is not None:
                self._meta.app_version = event.app_version
            if event.git_rev is not None:
                self._meta.git_rev = event.git_rev
            return
        if isinstance(event, SetContextEvent):
            self._context[normalize_context_key(event.name)] = deepcopy(event.value)
            return
        if isinstance(event, AddOpEvent):
            name = normalize_op_key(event.name)
            entry = self._summary.ops.setdefault(name, {"ok": 0, "failed": 0, "count": 0})
            entry["ok"] += int(event.ok)
            entry["failed"] += int(event.failed)
            entry["count"] += int(event.count)
            return
        if isinstance(event, MergeOpFieldsEvent):
            name = normalize_op_key(event.name)
            entry = self._summary.ops.setdefault(name, {})
            for key, value in event.values.items():
                entry[str(key)] = int(value)
            return
        if isinstance(event, SetRowCountersEvent):
            self._summary.rows_total = int(event.rows_total)
            self._summary.rows_passed = int(event.rows_passed)
            self._summary.rows_blocked = int(event.rows_blocked)
            self._summary.rows_with_warnings = int(event.rows_with_warnings)
            self._summary.rows_skipped = int(event.rows_skipped)
            return
        if isinstance(event, AddItemEvent):
            self._apply_add_item(event)
            return
        if isinstance(event, SetItemsTruncatedEvent):
            self._meta.items_truncated = bool(event.value)
            return
        if isinstance(event, EnsureErrorsTotalAtLeastEvent):
            if self._summary.errors_total < int(event.value):
                self._summary.errors_total = int(event.value)
            return
        if isinstance(event, SetStatusEvent):
            self._status = event.status
            return
        if isinstance(event, FinishEvent):
            self._meta.finished_at = event.finished_at or get_now_iso()
            self._meta.duration_ms = event.duration_ms
            if self._status is None:
                self._status = self._derive_status()
            return
        if isinstance(event, ActivityMetricEvent):
            activity = dict(self._context.get(ReportContextKey.STATS.value, {}))
            activity[event.name] = dict(event.payload)
            self._context[ReportContextKey.STATS.value] = activity
            return
        raise TypeError(f"Unsupported report event: {type(event).__name__}")

    def snapshot(self) -> ReportEnvelope:
        """
        Назначение:
            Вернуть изолированный snapshot текущего состояния отчёта.
        """
        return ReportEnvelope(
            status=self._status or self._derive_status(),
            meta=deepcopy(self._meta),
            summary=deepcopy(self._summary),
            items=deepcopy(self._items),
            context=deepcopy(self._context),
        )

    def meta_snapshot(self) -> ReportMeta:
        return deepcopy(self._meta)

    def summary_snapshot(self) -> ReportSummary:
        return deepcopy(self._summary)

    def items_snapshot(self) -> list[ReportItem]:
        return deepcopy(self._items)

    def context_snapshot(self) -> dict[str, Any]:
        return deepcopy(self._context)

    def status_snapshot(self) -> str | None:
        return self._status

    def _apply_add_item(self, event: AddItemEvent) -> None:
        status = normalize_item_status(event.status)
        error_list = list(event.errors)
        warning_list = list(event.warnings)

        if not event.preaggregated:
            self._summary.rows_total += 1
            if status == ReportItemStatus.FAILED:
                self._summary.rows_blocked += 1
            elif status == ReportItemStatus.OK:
                self._summary.rows_passed += 1
            elif status == ReportItemStatus.SKIPPED:
                self._summary.rows_skipped += 1
            if warning_list:
                self._summary.rows_with_warnings += 1

        self._count_diagnostics(error_list, warning_list)

        if event.store and self._should_store_item():
            self._items.append(
                ReportItem(
                    status=status,
                    row_ref=event.row_ref,
                    payload=event.payload,
                    diagnostics=[*error_list, *warning_list],
                    meta=deepcopy(event.meta),
                )
            )
        elif event.store:
            self._meta.items_truncated = True

    def _should_store_item(self) -> bool:
        limit = self._meta.items_limit
        if limit is None:
            return True
        return len(self._items) < limit

    def _count_diagnostics(self, errors: list[Any], warnings: list[Any]) -> None:
        self._summary.errors_total += len(errors)
        self._summary.warnings_total += len(warnings)
        for error in errors:
            self._count_stage(getattr(error, "stage", None), "errors_total")
        for warning in warnings:
            self._count_stage(getattr(warning, "stage", None), "warnings_total")

    def _count_stage(self, stage: DiagnosticStage | str | None, field: str) -> None:
        if stage is None:
            key = "UNKNOWN"
        elif isinstance(stage, DiagnosticStage):
            key = stage.value
        else:
            key = str(stage)
        entry = self._summary.by_stage.setdefault(key, {"errors_total": 0, "warnings_total": 0})
        entry[field] += 1

    def _derive_status(self) -> str:
        if self._summary.rows_blocked == 0:
            return "SUCCESS"
        if self._summary.rows_passed > 0:
            return "PARTIAL"
        return "FAILED"


def asdict_envelope(envelope: ReportEnvelope) -> dict[str, Any]:
    """
    Назначение:
        Безопасная сериализация ReportEnvelope с enum-полями.
    """
    return {
        "status": envelope.status,
        "meta": asdict(envelope.meta),
        "summary": asdict(envelope.summary),
        "items": [
            {
                "status": item.status.value,
                "row_ref": asdict(item.row_ref) if item.row_ref else None,
                "payload": item.payload,
                "diagnostics": [asdict(diag) for diag in item.diagnostics],
                "meta": item.meta,
            }
            for item in envelope.items
        ],
        "context": envelope.context,
    }
