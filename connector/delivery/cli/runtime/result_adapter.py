"""
Назначение:
    Runtime helper-функции для canonical `DomainCommandResult`.

Граница ответственности:
    - Не содержит compatibility-веток устаревших runtime-результатов.
    - Не пишет в report и не управляет lifecycle.
"""

from __future__ import annotations

from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.diagnostics.policies import SystemErrorCode


def result_with(code: SystemErrorCode) -> DomainCommandResult:
    """
    Назначение:
        Собрать `DomainCommandResult` с одиночным системным кодом.
    """
    result = DomainCommandResult()
    result.add_code(code)
    return result


def exit_code_from_result(result: DomainCommandResult | None) -> int:
    """
    Назначение:
        Получить OS exit code из canonical runtime результата.
    """
    if result is None:
        return 0
    if not isinstance(result, DomainCommandResult):
        raise TypeError(
            "Runtime result must be DomainCommandResult | None; "
            f"got {type(result).__name__}"
        )
    return result.exit_code()


__all__ = [
    "exit_code_from_result",
    "result_with",
]
