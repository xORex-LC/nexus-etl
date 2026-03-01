"""
Назначение:
    Bridge-адаптер ReportWritePort -> IReportSink на окно совместимости DEC-001/003.

Граница ответственности:
    - Предоставляет legacy write API (`set_meta/add_item/...`) для текущих usecase/handlers.
    - Внутри транслирует вызовы в event-driven sink через `emit(event)`.
    - Не владеет состоянием отчёта; owner состояния — IReportContext.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from connector.domain.models import RowRef
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import IReportContext
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, ReportOpKey
from connector.domain.reporting.events import (
    AddItemEvent,
    AddOpEvent,
    EnsureErrorsTotalAtLeastEvent,
    FinishEvent,
    MergeOpFieldsEvent,
    SetContextEvent,
    SetItemsTruncatedEvent,
    SetMetaEvent,
    SetRowCountersEvent,
    SetStatusEvent,
)
from connector.domain.reporting.models import ReportDiagnostic, ReportEnvelope, ReportItem, ReportMeta, ReportSummary
from connector.domain.reporting.ports import ReportWritePort
from connector.domain.reporting.sink import IReportSink


class ReportWritePortBridge(ReportWritePort):
    """
    Назначение:
        Совместимый write/read API поверх event-driven sink/context.

    Совместимость:
        - Используется как переходный слой до полного cutover на `IReportSink.emit(...)`.
        - Сохраняет properties `meta/summary/items/context/status` и `build()`
          для существующих runtime/usecase сценариев.
    """

    def __init__(
        self,
        *,
        sink: IReportSink,
        context: IReportContext,
        assembler: ReportAssembler,
    ) -> None:
        self._sink = sink
        self._context = context
        self._assembler = assembler

    @property
    def meta(self) -> ReportMeta:
        return self._context.meta_snapshot()

    @property
    def summary(self) -> ReportSummary:
        return self._context.summary_snapshot()

    @property
    def items(self) -> list[ReportItem]:
        return self._context.items_snapshot()

    @property
    def context(self) -> dict[str, Any]:
        return self._context.context_snapshot()

    @property
    def status(self) -> str | None:
        return self._context.status_snapshot()

    def set_meta(
        self,
        *,
        dataset: str | None = None,
        items_limit: int | None = None,
        app_version: str | None = None,
        git_rev: str | None = None,
    ) -> None:
        self._sink.emit(
            SetMetaEvent(
                dataset=dataset,
                items_limit=items_limit,
                app_version=app_version,
                git_rev=git_rev,
            )
        )

    def set_context(self, name: ReportContextKey | str, value: dict[str, Any]) -> None:
        self._sink.emit(SetContextEvent(name=name, value=deepcopy(value)))

    def get_context(self, name: ReportContextKey | str, default: Any = None) -> Any:
        key = name.value if isinstance(name, ReportContextKey) else str(name)
        context_snapshot = self._context.context_snapshot()
        if key not in context_snapshot:
            return deepcopy(default)
        return deepcopy(context_snapshot[key])

    def add_op(
        self,
        name: ReportOpKey | str,
        *,
        ok: int = 0,
        failed: int = 0,
        count: int = 0,
    ) -> None:
        self._sink.emit(AddOpEvent(name=name, ok=ok, failed=failed, count=count))

    def merge_op_fields(self, name: ReportOpKey | str, values: Mapping[str, int]) -> None:
        self._sink.emit(MergeOpFieldsEvent(name=name, values=dict(values)))

    def set_row_counters(
        self,
        *,
        rows_total: int,
        rows_passed: int,
        rows_blocked: int,
        rows_with_warnings: int,
        rows_skipped: int = 0,
    ) -> None:
        self._sink.emit(
            SetRowCountersEvent(
                rows_total=int(rows_total),
                rows_passed=int(rows_passed),
                rows_blocked=int(rows_blocked),
                rows_with_warnings=int(rows_with_warnings),
                rows_skipped=int(rows_skipped),
            )
        )

    def add_item(
        self,
        *,
        status: ReportItemStatus | str,
        row_ref: RowRef | None = None,
        payload: Mapping[str, Any] | None = None,
        errors: Iterable[ReportDiagnostic] | None = None,
        warnings: Iterable[ReportDiagnostic] | None = None,
        meta: dict[str, Any] | None = None,
        store: bool = True,
    ) -> None:
        self._sink.emit(
            AddItemEvent(
                status=status,
                row_ref=row_ref,
                payload=payload,
                errors=tuple(errors or ()),
                warnings=tuple(warnings or ()),
                meta=deepcopy(meta or {}),
                store=bool(store),
                preaggregated=False,
            )
        )

    def add_item_preaggregated(
        self,
        *,
        status: ReportItemStatus | str,
        row_ref: RowRef | None = None,
        payload: Mapping[str, Any] | None = None,
        errors: Iterable[ReportDiagnostic] | None = None,
        warnings: Iterable[ReportDiagnostic] | None = None,
        meta: dict[str, Any] | None = None,
        store: bool = True,
    ) -> None:
        self._sink.emit(
            AddItemEvent(
                status=status,
                row_ref=row_ref,
                payload=payload,
                errors=tuple(errors or ()),
                warnings=tuple(warnings or ()),
                meta=deepcopy(meta or {}),
                store=bool(store),
                preaggregated=True,
            )
        )

    def set_items_truncated(self, value: bool = True) -> None:
        self._sink.emit(SetItemsTruncatedEvent(value=bool(value)))

    def ensure_errors_total_at_least(self, value: int) -> None:
        self._sink.emit(EnsureErrorsTotalAtLeastEvent(value=int(value)))

    def set_status(self, status: str | None) -> None:
        self._sink.emit(SetStatusEvent(status=status))

    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None:
        self._sink.emit(FinishEvent(finished_at=finished_at, duration_ms=duration_ms))

    def build(self) -> ReportEnvelope:
        return self._assembler.assemble()
