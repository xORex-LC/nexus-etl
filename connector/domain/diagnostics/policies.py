"""
Назначение:
    Политики системных кодов и маппинг статусов.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SystemErrorCode(str, Enum):
    """
    Назначение:
        Небольшая таксономия системных кодов для политик (retry/stop/exit).
    """

    OK = "OK"
    UNKNOWN_CODE = "UNKNOWN_CODE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATA_INVALID = "DATA_INVALID"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    CONFLICT = "CONFLICT"
    INFRA_TIMEOUT = "INFRA_TIMEOUT"
    INFRA_UNAVAILABLE = "INFRA_UNAVAILABLE"
    IO_ERROR = "IO_ERROR"
    CACHE_ERROR = "CACHE_ERROR"


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
    SystemErrorCode.INFRA_TIMEOUT: "SINK_TIMEOUT",
    SystemErrorCode.IO_ERROR: "SINK_IO_ERROR",
    SystemErrorCode.INFRA_UNAVAILABLE: "SINK_UNAVAILABLE",
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

FATAL_PRIORITY: tuple[SystemErrorCode, ...] = (
    SystemErrorCode.INTERNAL_ERROR,
    SystemErrorCode.AUTH_UNAUTHORIZED,
    SystemErrorCode.AUTH_FORBIDDEN,
)

EXIT_CODE_MAP: dict[SystemErrorCode, int] = {
    SystemErrorCode.OK: 0,
    SystemErrorCode.DATA_INVALID: 1,
    SystemErrorCode.CONFLICT: 1,
    SystemErrorCode.AUTH_UNAUTHORIZED: 2,
    SystemErrorCode.AUTH_FORBIDDEN: 2,
    SystemErrorCode.CACHE_ERROR: 2,
    SystemErrorCode.IO_ERROR: 2,
    SystemErrorCode.INFRA_TIMEOUT: 2,
    SystemErrorCode.INFRA_UNAVAILABLE: 2,
    SystemErrorCode.INTERNAL_ERROR: 2,
    SystemErrorCode.UNKNOWN_CODE: 2,
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


def map_http_status(status_code: int | None) -> SystemErrorCode:
    """
    Назначение:
        Преобразовать HTTP-статус в SystemErrorCode.
    """
    explicit = {
        401: SystemErrorCode.AUTH_UNAUTHORIZED,
        403: SystemErrorCode.AUTH_FORBIDDEN,
        409: SystemErrorCode.CONFLICT,
    }
    if status_code in explicit:
        return explicit[status_code]
    if status_code is None:
        return SystemErrorCode.INTERNAL_ERROR
    if 400 <= status_code < 500:
        return SystemErrorCode.DATA_INVALID
    if status_code >= 500:
        return SystemErrorCode.INFRA_UNAVAILABLE
    return SystemErrorCode.INTERNAL_ERROR


def resolve_primary_code(
    codes: set[SystemErrorCode],
    stop_policy: StopPolicy,
) -> SystemErrorCode:
    """
    Назначение:
        Выбрать главный SystemErrorCode из множества.
    """
    if not codes:
        return SystemErrorCode.OK
    if SystemErrorCode.OK in codes and len(codes) == 1:
        return SystemErrorCode.OK
    for code in FATAL_PRIORITY:
        if code in codes and stop_policy.is_fatal(code):
            return code
    # Учитываем кастомные fatal-коды из stop_policy вне фиксированного приоритета.
    for code in sorted(codes, key=lambda c: c.value):
        if stop_policy.is_fatal(code):
            return code
    if SystemErrorCode.DATA_INVALID in codes:
        return SystemErrorCode.DATA_INVALID
    if SystemErrorCode.CONFLICT in codes:
        return SystemErrorCode.CONFLICT
    return sorted(codes, key=lambda c: c.value)[0]
