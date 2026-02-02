from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.diagnostics.exceptions import DiagnosticContextNotConfiguredError
from connector.domain.diagnostics.policies import (
    ExitCodePolicy,
    RetryPolicy,
    StopPolicy,
    default_exit_policy,
    default_retry_policy,
    default_stop_policy,
)
from connector.domain.diagnostics.translator import Translator
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef


@dataclass(frozen=True)
class DiagnosticContext:
    """
    Назначение:
        Контекст диагностики для одного run/usecase.
    """

    catalog: Any
    factory: DiagnosticFactory
    translator: Translator
    retry_policy: RetryPolicy
    stop_policy: StopPolicy
    exit_policy: ExitCodePolicy

    @classmethod
    def from_factory(
        cls,
        factory: DiagnosticFactory,
        *,
        retry_policy: RetryPolicy | None = None,
        stop_policy: StopPolicy | None = None,
        exit_policy: ExitCodePolicy | None = None,
    ) -> "DiagnosticContext":
        return cls(
            catalog=factory.catalog,
            factory=factory,
            translator=Translator(factory.catalog),
            retry_policy=retry_policy or default_retry_policy(),
            stop_policy=stop_policy or default_stop_policy(),
            exit_policy=exit_policy or default_exit_policy(),
        )

    @classmethod
    def from_catalog(
        cls,
        catalog,
        *,
        retry_policy: RetryPolicy | None = None,
        stop_policy: StopPolicy | None = None,
        exit_policy: ExitCodePolicy | None = None,
    ) -> "DiagnosticContext":
        factory = DiagnosticFactory(catalog)
        return cls(
            catalog=catalog,
            factory=factory,
            translator=Translator(catalog),
            retry_policy=retry_policy or default_retry_policy(),
            stop_policy=stop_policy or default_stop_policy(),
            exit_policy=exit_policy or default_exit_policy(),
        )


_context_var: ContextVar[DiagnosticContext | None] = ContextVar("diagnostic_context", default=None)


def configure(ctx: DiagnosticContext | DiagnosticFactory) -> DiagnosticContext:
    """
    Назначение:
        Зарегистрировать диагностический контекст в текущем контексте.
    """
    if isinstance(ctx, DiagnosticFactory):
        ctx = DiagnosticContext.from_factory(ctx)
    _context_var.set(ctx)
    return ctx


def get_context(ctx: DiagnosticContext | None = None) -> DiagnosticContext:
    """
    Назначение:
        Получить текущий диагностический контекст.
    """
    if ctx is not None:
        return ctx
    context = _context_var.get()
    if context is None:
        raise DiagnosticContextNotConfiguredError()
    return context


def get_factory(ctx: DiagnosticContext | None = None) -> DiagnosticFactory:
    """
    Назначение:
        Получить фабрику диагностик из текущего контекста.
    """
    return get_context(ctx).factory


def get_translator(ctx: DiagnosticContext | None = None) -> Translator:
    """
    Назначение:
        Получить translator из текущего контекста.
    """
    return get_context(ctx).translator


def error(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
    ctx: DiagnosticContext | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (error) через текущую фабрику.
    """
    return get_factory(ctx).error(
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )


def warning(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
    ctx: DiagnosticContext | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (warning) через текущую фабрику.
    """
    return get_factory(ctx).warning(
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )
