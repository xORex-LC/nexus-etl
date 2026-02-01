from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from connector.domain.models import DiagnosticSeverity
from connector.domain.diagnostics.system_codes import SystemErrorCode
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
