"""
Реестр компиляторов transport-операций для target-core.

Назначение:
    Развязать TargetKernel от конкретных transport-реализаций (HTTP и др.).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from connector.infra.target.core.spec_models import OperationSpec


class CompiledOperation(Protocol):
    """Скомпилированная операция конкретного транспорта."""

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> Any: ...


OperationCompiler = Callable[[OperationSpec], CompiledOperation]


class TransportCompilerRegistry:
    """Реестр компиляторов по `operation.kind`."""

    def __init__(self) -> None:
        self._compilers: dict[str, OperationCompiler] = {}

    def register(self, kind: str, compiler: OperationCompiler) -> None:
        normalized = kind.strip().lower()
        if normalized == "":
            raise ValueError("kind транспорта не должен быть пустым")
        self._compilers[normalized] = compiler

    def compile(self, operation: OperationSpec) -> CompiledOperation:
        compiler = self._compilers.get(operation.kind)
        if compiler is None:
            raise ValueError(
                f"для operation.kind={operation.kind!r} не зарегистрирован компилятор",
            )
        return compiler(operation)
