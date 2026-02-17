"""
Реестр компиляторов transport-операций для target-core.

Назначение:
    Развязать TargetKernel от конкретных transport-реализаций (HTTP и др.).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar

from connector.infra.target.core.spec_models import OperationSpec

TCompiledRequest = TypeVar("TCompiledRequest")


class CompiledOperation(Protocol[TCompiledRequest]):
    """Скомпилированная операция конкретного транспорта.

    Контракт:
        - принимает runtime-параметры операции;
        - возвращает transport-specific запрос, opaque для target-core.
    """

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> TCompiledRequest: ...


OperationCompiler = Callable[[OperationSpec], CompiledOperation[Any]]


class TransportCompilerRegistry:
    """Реестр компиляторов по ``operation.kind``."""

    def __init__(self) -> None:
        self._compilers: dict[str, OperationCompiler] = {}

    def register(self, kind: str, compiler: OperationCompiler) -> None:
        """Зарегистрировать compiler для transport kind."""
        normalized = kind.strip().lower()
        if normalized == "":
            raise ValueError("kind транспорта не должен быть пустым")
        self._compilers[normalized] = compiler

    def compile(self, operation: OperationSpec) -> CompiledOperation[Any]:
        """Скомпилировать operation в transport-specific объект.

        Raises:
            ValueError: если для ``operation.kind`` не зарегистрирован compiler.
        """
        compiler = self._compilers.get(operation.kind)
        if compiler is None:
            raise ValueError(
                f"для operation.kind={operation.kind!r} не зарегистрирован компилятор",
            )
        return compiler(operation)
