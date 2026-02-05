"""
Назначение:
    Каталог диагностических кодов и фабрики DiagnosticItem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.diagnostics.exceptions import UnknownDiagnosticCodeError


@dataclass(frozen=True)
class CatalogEntry:
    """
    Назначение:
        Описание диагностического кода и его системной классификации.

    Поля:
        diag_code: строковый диагностический код.
        system_code: агрегированный системный код (для политики/exit code).
        default_message: дефолтное сообщение (если не задано при создании события).
        severity: дефолтная severity для кода.
        retryable: флаг ретрая (policy-подсказка).
        fatal: флаг фатальности (policy-подсказка).
    """

    diag_code: str
    system_code: SystemErrorCode
    default_message: str | None = None
    severity: DiagnosticSeverity | None = None
    retryable: bool = False
    fatal: bool = False


class ErrorCatalog:
    """
    Назначение:
        Центральный реестр диагностических кодов и их классификации.

    Инварианты/гарантии:
        - В strict режиме неизвестный код вызывает исключение.
        - В permissive режиме неизвестный код классифицируется как UNKNOWN_CODE.
    """

    def __init__(self, entries: Iterable[CatalogEntry] | None = None, *, strict: bool = False) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        self.strict = strict
        if entries:
            for entry in entries:
                self.register(entry)

    def with_strict(self, strict: bool) -> "ErrorCatalog":
        """
        Назначение:
            Вернуть копию каталога с иным режимом strict.
        """
        catalog = ErrorCatalog(strict=strict)
        catalog.register_many(self._entries.values())
        return catalog

    def contains(self, diag_code: str) -> bool:
        """
        Назначение:
            Проверить наличие кода в каталоге.
        """
        return diag_code in self._entries

    def merge(self, other: "ErrorCatalog", *, on_conflict: str = "error") -> "ErrorCatalog":
        """
        Назначение:
            Объединить два каталога в новый.
        Параметры:
            on_conflict:
                "error" — выбросить исключение при конфликте кода,
                "override" — использовать запись из other.
        """
        merged = ErrorCatalog(strict=self.strict or other.strict)
        merged.register_many(self._entries.values())
        for entry in other._entries.values():
            if entry.diag_code in merged._entries and on_conflict != "override":
                raise ValueError(f"Duplicate diagnostic code: {entry.diag_code}")
            merged._entries[entry.diag_code] = entry
        return merged

    def register(self, entry: CatalogEntry) -> None:
        """
        Назначение:
            Зарегистрировать диагностический код.
        """
        self._entries[entry.diag_code] = entry

    def register_many(self, entries: Iterable[CatalogEntry]) -> None:
        """
        Назначение:
            Зарегистрировать несколько диагностических кодов.
        """
        for entry in entries:
            self.register(entry)

    def get_entry(self, diag_code: str) -> CatalogEntry | None:
        """
        Назначение:
            Получить запись каталога по коду.
        """
        return self._entries.get(diag_code)

    def classify(self, diag_code: str) -> SystemErrorCode:
        """
        Назначение:
            Классифицировать диагностический код в системный.
        Ошибки/исключения:
            UnknownDiagnosticCodeError в strict режиме.
        """
        entry = self._entries.get(diag_code)
        if entry:
            return entry.system_code
        if self.strict:
            raise UnknownDiagnosticCodeError(diag_code)
        return SystemErrorCode.UNKNOWN_CODE

    def resolve_severity(
        self,
        diag_code: str,
        explicit: DiagnosticSeverity | None,
        fallback: DiagnosticSeverity,
    ) -> DiagnosticSeverity:
        """
        Назначение:
            Определить severity по приоритету:
            explicit -> entry.severity -> fallback.
        """
        if explicit is not None:
            return explicit
        entry = self._entries.get(diag_code)
        if entry and entry.severity is not None:
            return entry.severity
        return fallback

    def resolve_message(self, diag_code: str, explicit: str | None) -> str:
        """
        Назначение:
            Подобрать сообщение по приоритету:
            explicit -> entry.default_message -> diag_code.
        """
        if explicit:
            return explicit
        entry = self._entries.get(diag_code)
        if entry and entry.default_message:
            return entry.default_message
        return diag_code


def build_catalog(dataset: str | None, *, strict: bool) -> ErrorCatalog:
    """
    Назначение:
        Собрать итоговый каталог диагностик (core + dataset).

    Контракт:
        - dataset=None -> только core каталог.
        - dataset указан -> core + dataset catalog.
        - strict режим применяется единообразно.

    Ошибки/исключения:
        - ValueError при конфликте кодов (on_conflict=error).
    """
    from connector.domain.diagnostics.core_catalog import build_core_catalog
    from connector.datasets.registry import get_spec

    core = build_core_catalog(strict=strict)
    if dataset is None:
        return core
    spec = get_spec(dataset)
    dataset_catalog = spec.get_diagnostic_catalog(strict=strict)
    return core.merge(dataset_catalog, on_conflict="error")


def build_error(
    *,
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict | None = None,
    severity: DiagnosticSeverity | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem уровня ERROR через ErrorCatalog.
    """
    return DiagnosticItem.from_catalog(
        catalog=catalog,
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
        default_severity=DiagnosticSeverity.ERROR,
    )


def build_warning(
    *,
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict | None = None,
    severity: DiagnosticSeverity | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem уровня WARNING через ErrorCatalog.
    """
    return DiagnosticItem.from_catalog(
        catalog=catalog,
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
        default_severity=DiagnosticSeverity.WARNING,
    )
