"""Purpose:
    Boundary adapter для runtime handler результатов.

Boundary:
    - Нормализует handler/runtime return values в ограниченный набор видов.
    - Владеет compatibility window для legacy `CliCommandResult`/`int`.
    - Не пишет в report и не управляет orchestration lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from connector.delivery.cli.result import CommandResult as CliCommandResult
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.diagnostics.policies import SystemErrorCode


RuntimeResultKind = Literal[
    "none",
    "domain",
    "legacy_cli",
    "legacy_int",
    "exit_code_provider",
    "unknown",
]


@dataclass(frozen=True)
class AdaptedRuntimeResult:
    """Purpose:
        Нормализованное представление handler/runtime результата.
    """

    kind: RuntimeResultKind
    value: Any = None


def adapt_runtime_result(result: Any) -> AdaptedRuntimeResult:
    """Purpose:
        Классифицировать runtime результат для boundary processing.

    Compatibility:
        `legacy_cli` и `legacy_int` поддерживаются временно (DEC-004/005).
    """
    if result is None:
        return AdaptedRuntimeResult("none", None)
    if isinstance(result, DomainCommandResult):
        return AdaptedRuntimeResult("domain", result)
    if isinstance(result, CliCommandResult):
        return AdaptedRuntimeResult("legacy_cli", result)
    if isinstance(result, int):
        return AdaptedRuntimeResult("legacy_int", result)
    exit_code_fn = getattr(result, "exit_code", None)
    if callable(exit_code_fn):
        return AdaptedRuntimeResult("exit_code_provider", result)
    return AdaptedRuntimeResult("unknown", result)


def result_with(code: SystemErrorCode) -> DomainCommandResult:
    """Purpose:
        Собрать canonical `DomainCommandResult` с одиночным системным кодом.
    """
    result = DomainCommandResult()
    result.add_code(code)
    return result


def exit_code_from_result(result: Any) -> int:
    """Purpose:
        Получить OS exit code через единый boundary adapter.

    Contract:
        - Canonical path: `DomainCommandResult.exit_code()`.
        - Legacy compatibility path: `CliCommandResult` / `int`.
    """
    adapted = adapt_runtime_result(result)
    if adapted.kind == "none":
        return 0
    if adapted.kind == "domain":
        return adapted.value.exit_code()
    if adapted.kind == "legacy_int":
        return adapted.value
    if adapted.kind == "legacy_cli":
        if adapted.value.status == "ok":
            return 0
        if adapted.value.status == "warn":
            return 1
        return 2
    if adapted.kind == "exit_code_provider":
        return adapted.value.exit_code()
    return 2


__all__ = [
    "AdaptedRuntimeResult",
    "RuntimeResultKind",
    "adapt_runtime_result",
    "exit_code_from_result",
    "result_with",
]
