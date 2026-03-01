"""Purpose:
    Runtime-level контракты orchestration слоя CLI.

Boundary:
    - Фиксирует явный handler contract: `(ctx, opts, report_port)`.
    - Содержит only-runtime ошибки и null-object для report write boundary.
    - Не содержит orchestration/DI lifecycle и не маппит результаты в report.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, TypeAlias, runtime_checkable

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.result import CommandResult as CliCommandResult
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.models import RowRef
from connector.domain.reporting.models import ReportDiagnostic
from connector.domain.reporting.ports import ReportWritePort


RuntimeExecutionResult: TypeAlias = DomainCommandResult | CliCommandResult | int | None


@runtime_checkable
class CommandHandler(Protocol):
    """Purpose:
        Явный runtime контракт обработчика CLI-команды.

    Contract:
        - Runtime always вызывает handler с 3 аргументами.
        - `report_port` может быть `NullReportWritePort` в режимах без report.
    """

    def __call__(
        self,
        ctx: BoundCommandContext,
        opts: Any,
        report_port: ReportWritePort,
    ) -> RuntimeExecutionResult: ...


class RuntimeErrorWithCode(RuntimeError):
    """Purpose:
        Ошибка runtime-валидации с фиксированным exit code.
    """

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class NullReportWritePort(ReportWritePort):
    """Purpose:
        Null-object реализация `ReportWritePort` для run_without_report.

    Compatibility:
        Переходный адаптер совместимости (DEC-004/005), чтобы сохранять единый
        3-arg handler contract без event-driven sink cutover.
    """

    def set_meta(
        self,
        *,
        dataset: str | None = None,
        items_limit: int | None = None,
        app_version: str | None = None,
        git_rev: str | None = None,
    ) -> None:
        return None

    def set_context(self, name: str, value: dict[str, Any]) -> None:
        return None

    def get_context(self, name: str, default: Any = None) -> Any:
        return default

    def add_op(self, name: str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None:
        return None

    def merge_op_fields(self, name: str, values: Mapping[str, int]) -> None:
        return None

    def set_row_counters(
        self,
        *,
        rows_total: int,
        rows_passed: int,
        rows_blocked: int,
        rows_with_warnings: int,
    ) -> None:
        return None

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
    ) -> None:
        return None

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
    ) -> None:
        return None

    def set_items_truncated(self, value: bool = True) -> None:
        return None

    def ensure_errors_total_at_least(self, value: int) -> None:
        return None

    def set_status(self, status: str | None) -> None:
        return None

    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None:
        return None


__all__ = [
    "CommandHandler",
    "NullReportWritePort",
    "RuntimeErrorWithCode",
    "RuntimeExecutionResult",
]
