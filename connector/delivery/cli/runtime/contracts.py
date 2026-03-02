"""
Назначение:
    Runtime-level контракты orchestration слоя CLI.

Граница ответственности:
    - Фиксирует явный handler contract: `(ctx, opts, report_sink)`.
    - Содержит only-runtime ошибки и null-object для report write boundary.
    - Не содержит orchestration/DI lifecycle и не маппит результаты в report.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias, runtime_checkable

from connector.delivery.cli.context import BoundCommandContext
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.reporting.sink import IReportSink


RuntimeExecutionResult: TypeAlias = DomainCommandResult | None


@runtime_checkable
class CommandHandler(Protocol):
    """
    Назначение:
        Явный runtime контракт обработчика CLI-команды.

    Контракт:
        - Runtime always вызывает handler с 3 аргументами.
        - `report_sink` может быть `NullReportSink` в режимах без report.
    """

    def __call__(
        self,
        ctx: BoundCommandContext,
        opts: Any,
        report_sink: IReportSink,
    ) -> RuntimeExecutionResult: ...


class RuntimeErrorWithCode(RuntimeError):
    """
    Назначение:
        Ошибка runtime-валидации с фиксированным exit code.
    """

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


__all__ = [
    "CommandHandler",
    "RuntimeErrorWithCode",
    "RuntimeExecutionResult",
]
