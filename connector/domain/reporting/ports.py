"""Purpose:
    Контракты записи в report-layer.

Boundary:
    - Определяет write-boundary для delivery/usecase компонентов.
    - Не хранит состояние и не знает о формате артефактов.
    - Используется как переходный bridge (DEC-003) до полного event-driven
      ingestion через IReportSink (DEC-001).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from connector.domain.models import RowRef
from connector.domain.reporting.models import ReportDiagnostic


@runtime_checkable
class ReportWritePort(Protocol):
    """Purpose:
        Публичный контракт записи в отчет для внешних компонентов.

    Contract:
        - Запись выполняется только через методы порта.
        - Внешний код не должен мутировать внутренние структуры collector.
        - Методы `set_row_counters()` и `add_item_preaggregated()` сохранены как
          compatibility-bridge для pre-aggregated apply-flow.
    """

    def set_meta(
        self,
        *,
        dataset: str | None = None,
        items_limit: int | None = None,
        app_version: str | None = None,
        git_rev: str | None = None,
    ) -> None: ...

    def set_context(self, name: str, value: dict[str, Any]) -> None: ...

    def get_context(self, name: str, default: Any = None) -> Any: ...

    def add_op(self, name: str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None: ...

    def merge_op_fields(self, name: str, values: Mapping[str, int]) -> None: ...

    def set_row_counters(
        self,
        *,
        rows_total: int,
        rows_passed: int,
        rows_blocked: int,
        rows_with_warnings: int,
    ) -> None: ...

    def add_item(
        self,
        *,
        status: str,
        row_ref: RowRef | None = None,
        payload: Mapping[str, Any] | None = None,
        errors: Iterable[ReportDiagnostic] | None = None,
        warnings: Iterable[ReportDiagnostic] | None = None,
        meta: dict[str, Any] | None = None,
        store: bool = True,
    ) -> None: ...

    def add_item_preaggregated(
        self,
        *,
        status: str,
        row_ref: RowRef | None = None,
        payload: Mapping[str, Any] | None = None,
        errors: Iterable[ReportDiagnostic] | None = None,
        warnings: Iterable[ReportDiagnostic] | None = None,
        meta: dict[str, Any] | None = None,
        store: bool = True,
    ) -> None: ...

    def set_items_truncated(self, value: bool = True) -> None: ...

    def ensure_errors_total_at_least(self, value: int) -> None: ...

    def set_status(self, status: str | None) -> None: ...

    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None: ...
