"""Purpose:
    In-memory сборщик report envelope и агрегированных метрик.

Boundary:
    - Владеет внутренним mutable state отчёта.
    - Предоставляет только API-методы записи (инкапсуляция DEC-003).
    - Не отвечает за runtime orchestration и не рендерит артефакт.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Iterable, Mapping

from connector.common.time import getNowIso
from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.reporting.contracts import (
    ReportContextKey,
    ReportItemStatus,
    ReportOpKey,
    normalize_context_key,
    normalize_item_status,
    normalize_op_key,
)
from connector.domain.reporting.models import (
    ReportDiagnostic,
    ReportEnvelope,
    ReportItem,
    ReportMeta,
    ReportSummary,
)


class ReportCollector:
    """Purpose:
        Единый owner состояния отчёта и его инвариантов.

    Invariants:
        - Внешние writers записывают данные только через public API.
        - `build()` возвращает snapshot, не разделяющий mutable ссылки с collector.
    """

    def __init__(self, run_id: str, command: str, started_at: str | None = None) -> None:
        self._meta = ReportMeta(
            run_id=run_id,
            dataset=None,
            command=command,
            started_at=started_at or getNowIso(),
        )
        self._summary = ReportSummary()
        self._items: list[ReportItem] = []
        self._context: dict[str, Any] = {}
        self._status: str | None = None

    @property
    def meta(self) -> ReportMeta:
        """Purpose:
            Read-only snapshot метаданных.
        """
        return deepcopy(self._meta)

    @property
    def summary(self) -> ReportSummary:
        """Purpose:
            Read-only snapshot агрегатов summary.
        """
        return deepcopy(self._summary)

    @property
    def items(self) -> list[ReportItem]:
        """Purpose:
            Read-only snapshot row-items.
        """
        return deepcopy(self._items)

    @property
    def context(self) -> dict[str, Any]:
        """Purpose:
            Read-only snapshot контекста отчёта.
        """
        return deepcopy(self._context)

    @property
    def status(self) -> str | None:
        """Purpose:
            Текущий фиксированный статус, если задан явно.
        """
        return self._status

    def set_meta(
        self,
        *,
        dataset: str | None = None,
        items_limit: int | None = None,
        app_version: str | None = None,
        git_rev: str | None = None,
    ) -> None:
        """Purpose:
            Обновить meta-поля отчёта через инкапсулированный API.
        """
        if dataset is not None:
            self._meta.dataset = dataset
        if items_limit is not None:
            self._meta.items_limit = items_limit
        if app_version is not None:
            self._meta.app_version = app_version
        if git_rev is not None:
            self._meta.git_rev = git_rev

    def set_context(self, name: ReportContextKey | str, value: dict[str, Any]) -> None:
        """Purpose:
            Установить namespaced context block.
        """
        key = normalize_context_key(name)
        self._context[key] = deepcopy(value)

    def get_context(self, name: ReportContextKey | str, default: Any = None) -> Any:
        """Purpose:
            Получить snapshot context block без утечки mutable ссылок.
        """
        key = normalize_context_key(name)
        if key not in self._context:
            return deepcopy(default)
        return deepcopy(self._context[key])

    def add_op(self, name: ReportOpKey | str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None:
        """Purpose:
            Инкрементировать стандартные counters операции.
        """
        op_name = normalize_op_key(name)
        entry = self._summary.ops.setdefault(op_name, {"ok": 0, "failed": 0, "count": 0})
        entry["ok"] += ok
        entry["failed"] += failed
        entry["count"] += count

    def merge_op_fields(self, name: ReportOpKey | str, values: Mapping[str, int]) -> None:
        """Purpose:
            Merge произвольных op-полей без прямой мутации summary.ops снаружи.
        """
        op_name = normalize_op_key(name)
        entry = self._summary.ops.setdefault(op_name, {})
        for key, value in values.items():
            entry[str(key)] = int(value)

    def set_row_counters(
        self,
        *,
        rows_total: int,
        rows_passed: int,
        rows_blocked: int,
        rows_with_warnings: int,
        rows_skipped: int = 0,
    ) -> None:
        """Purpose:
            Compatibility bridge для pre-aggregated сценариев (import-apply).

        Contract:
            - Используется только когда row-counters уже посчитаны вне collector.
            - Не влияет на diagnostics totals.
        """
        self._summary.rows_total = int(rows_total)
        self._summary.rows_passed = int(rows_passed)
        self._summary.rows_blocked = int(rows_blocked)
        self._summary.rows_skipped = int(rows_skipped)
        self._summary.rows_with_warnings = int(rows_with_warnings)

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
        """
        Назначение:
            Добавить элемент отчёта и обновить summary.

        Алгоритм:
            - Обновляет счётчики по статусу/diagnostics.
            - Учитывает items_limit и выставляет items_truncated.
        """
        normalized_status = normalize_item_status(status)
        error_list = list(errors or [])
        warning_list = list(warnings or [])

        self._summary.rows_total += 1
        if normalized_status == ReportItemStatus.FAILED:
            self._summary.rows_blocked += 1
        elif normalized_status == ReportItemStatus.OK:
            self._summary.rows_passed += 1
        elif normalized_status == ReportItemStatus.SKIPPED:
            self._summary.rows_skipped += 1
        if warning_list:
            self._summary.rows_with_warnings += 1

        self._count_diagnostics(error_list, warning_list)

        if store and self._should_store_item():
            self._append_item(
                status=normalized_status,
                row_ref=row_ref,
                payload=payload,
                error_list=error_list,
                warning_list=warning_list,
                meta=meta,
            )
        elif store:
            self._meta.items_truncated = True

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
        """Purpose:
            Compatibility bridge для pre-aggregated row-summary потоков.

        Contract:
            - Не изменяет `rows_total/rows_passed/rows_blocked/rows_with_warnings`.
            - Учитывает diagnostics totals через canonical collector logic.
            - Используется в import-apply до полного event-driven cutover.
        """
        error_list = list(errors or [])
        warning_list = list(warnings or [])
        self._count_diagnostics(error_list, warning_list)
        if store and self._should_store_item():
            self._append_item(
                status=normalize_item_status(status),
                row_ref=row_ref,
                payload=payload,
                error_list=error_list,
                warning_list=warning_list,
                meta=meta,
            )
        elif store:
            self._meta.items_truncated = True

    def set_items_truncated(self, value: bool = True) -> None:
        """Purpose:
            Явно выставить флаг truncation через API вместо прямой мутации meta.
        """
        self._meta.items_truncated = bool(value)

    def ensure_errors_total_at_least(self, value: int) -> None:
        """Purpose:
            Зафиксировать минимальный уровень errors_total для truncated outcomes.
        """
        min_value = int(value)
        if self._summary.errors_total < min_value:
            self._summary.errors_total = min_value

    def set_status(self, status: str | None) -> None:
        """Purpose:
            Явно задать статус отчёта для pre-aggregated сценариев.
        """
        self._status = status

    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None:
        self._meta.finished_at = finished_at or getNowIso()
        self._meta.duration_ms = duration_ms
        if self._status is None:
            self._status = self._derive_status()

    def build(self) -> ReportEnvelope:
        """Purpose:
            Вернуть изолированный snapshot report envelope.

        Contract:
            - Возвращаемые структуры не разделяют mutable ссылки с collector.
            - Пост-мутация collector не меняет уже построенный envelope.
        """
        return ReportEnvelope(
            status=self._status or self._derive_status(),
            meta=deepcopy(self._meta),
            summary=deepcopy(self._summary),
            items=deepcopy(self._items),
            context=deepcopy(self._context),
        )

    def _should_store_item(self) -> bool:
        limit = self._meta.items_limit
        if limit is None:
            return True
        return len(self._items) < limit

    def _derive_status(self) -> str:
        """Назначение:
            Вывести итоговый статус по агрегированным row-счётчикам.

        Контракт:
            - `rows_blocked == 0` -> SUCCESS.
            - Есть и passed, и blocked -> PARTIAL.
            - Есть blocked и нет passed -> FAILED.
        """
        if self._summary.rows_blocked == 0:
            return "SUCCESS"
        if self._summary.rows_passed > 0:
            return "PARTIAL"
        return "FAILED"

    def _append_item(
        self,
        *,
        status: ReportItemStatus,
        row_ref: RowRef | None,
        payload: Mapping[str, Any] | None,
        error_list: list[ReportDiagnostic],
        warning_list: list[ReportDiagnostic],
        meta: dict[str, Any] | None,
    ) -> None:
        diagnostics = [*error_list, *warning_list]
        self._items.append(
            ReportItem(
                status=status,
                row_ref=row_ref,
                payload=payload,
                diagnostics=diagnostics,
                meta=deepcopy(meta or {}),
            )
        )

    def _count_diagnostics(
        self,
        errors: list[ReportDiagnostic],
        warnings: list[ReportDiagnostic],
    ) -> None:
        self._summary.errors_total += len(errors)
        self._summary.warnings_total += len(warnings)
        for error in errors:
            self._count_stage(error.stage, "errors_total")
        for warning in warnings:
            self._count_stage(warning.stage, "warnings_total")

    def _count_stage(self, stage: DiagnosticStage, field: str) -> None:
        key = stage.value if isinstance(stage, DiagnosticStage) else str(stage)
        entry = self._summary.by_stage.setdefault(key, {"errors_total": 0, "warnings_total": 0})
        entry[field] += 1

    # Diagnostics are provided by the caller in report-ready form.


def asdict_report(envelope: ReportEnvelope) -> dict[str, Any]:
    """
    Назначение:
        Упрощённая сериализация без привязки к dataclasses.asdict.
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
