from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """
    Назначение:
        Единая таксономия кодов ошибок для ExecutionResult.
    """

    NETWORK_ERROR = "NETWORK_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_JSON = "INVALID_JSON"
    API_ERROR = "API_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    SECRET_REQUIRED = "SECRET_REQUIRED"
    SECRET_SOURCE_UNAVAILABLE = "SECRET_SOURCE_UNAVAILABLE"

    @classmethod
    def from_status(cls, status_code: int | None) -> "ErrorCode":
        """
        Назначение:
            Подбор общего кода по HTTP-статусу.
        """
        if status_code == 401:
            return cls.UNAUTHORIZED
        if status_code == 403:
            return cls.FORBIDDEN
        if status_code == 409:
            return cls.CONFLICT
        return cls.HTTP_ERROR
