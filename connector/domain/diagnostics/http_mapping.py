from __future__ import annotations

from connector.domain.diagnostics.system_codes import SystemErrorCode


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
