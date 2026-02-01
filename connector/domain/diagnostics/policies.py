from __future__ import annotations

from dataclasses import dataclass

from connector.domain.diagnostics.system_codes import SystemErrorCode


@dataclass(frozen=True)
class RetryPolicy:
    """
    Назначение:
        Политика повторных попыток на основе SystemErrorCode.
    """

    retryable: frozenset[SystemErrorCode]
    max_attempts: int

    def should_retry(self, sys_code: SystemErrorCode, attempt: int) -> bool:
        return sys_code in self.retryable and attempt < self.max_attempts


@dataclass(frozen=True)
class StopPolicy:
    """
    Назначение:
        Политика остановки пайплайна.
    """

    fatal: frozenset[SystemErrorCode]

    def is_fatal(self, sys_code: SystemErrorCode) -> bool:
        return sys_code in self.fatal

    def should_stop_fast(self, sys_code: SystemErrorCode, stop_on_first_error: bool) -> bool:
        return stop_on_first_error and self.is_fatal(sys_code)


@dataclass(frozen=True)
class ExitCodePolicy:
    """
    Назначение:
        Правило выбора exit code по SystemErrorCode.
    """

    mapping: dict[SystemErrorCode, int]
    default_code: int = 1

    def exit_code(self, sys_code: SystemErrorCode) -> int:
        return self.mapping.get(sys_code, self.default_code)
