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


SYSTEM_TO_DIAG: dict[SystemErrorCode, str] = {
    SystemErrorCode.AUTH_UNAUTHORIZED: "SINK_UNAUTHORIZED",
    SystemErrorCode.AUTH_FORBIDDEN: "SINK_FORBIDDEN",
    SystemErrorCode.CONFLICT: "SINK_CONFLICT",
}

RETRYABLE_CODES: frozenset[SystemErrorCode] = frozenset(
    {
        SystemErrorCode.INFRA_UNAVAILABLE,
        SystemErrorCode.INFRA_TIMEOUT,
    }
)

FATAL_CODES: frozenset[SystemErrorCode] = frozenset(
    {
        SystemErrorCode.AUTH_UNAUTHORIZED,
        SystemErrorCode.AUTH_FORBIDDEN,
        SystemErrorCode.INTERNAL_ERROR,
    }
)

EXIT_CODE_MAP: dict[SystemErrorCode, int] = {
    SystemErrorCode.OK: 0,
    SystemErrorCode.DATA_INVALID: 1,
    SystemErrorCode.CONFLICT: 1,
    SystemErrorCode.AUTH_UNAUTHORIZED: 2,
    SystemErrorCode.AUTH_FORBIDDEN: 2,
    SystemErrorCode.CACHE_ERROR: 2,
    SystemErrorCode.IO_ERROR: 2,
    SystemErrorCode.INFRA_TIMEOUT: 3,
    SystemErrorCode.INFRA_UNAVAILABLE: 3,
    SystemErrorCode.INTERNAL_ERROR: 4,
    SystemErrorCode.UNKNOWN_CODE: 4,
}


def default_retry_policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(retryable=RETRYABLE_CODES, max_attempts=max_attempts)


def default_stop_policy() -> StopPolicy:
    return StopPolicy(fatal=FATAL_CODES)


def default_exit_policy() -> ExitCodePolicy:
    return ExitCodePolicy(mapping=EXIT_CODE_MAP, default_code=1)


def map_system_code(system_code: SystemErrorCode | None) -> str:
    """
    Назначение:
        Преобразовать SystemErrorCode в диагностический код.
    """
    if system_code is None:
        return "SINK_HTTP_ERROR"
    return SYSTEM_TO_DIAG.get(system_code, "SINK_HTTP_ERROR")
