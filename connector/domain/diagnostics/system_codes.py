from __future__ import annotations

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
