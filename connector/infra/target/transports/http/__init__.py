"""Подсистема HTTP-транспорта (тонкий слой совместимости)."""

from __future__ import annotations

from connector.infra.target.transports.http.compiler import (
    compile_http_operation,
    compile_http_operation_data,
)
from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)
from connector.infra.target.transports.http.normalizer import (
    HttpNormalizedOutcome,
    normalize_http_outcome,
)
from connector.infra.target.transports.http.op_models import HttpOperationDataModel
from connector.infra.target.transports.http.request_builder import HttpRequest, build_http_request
from connector.infra.target.transports.http.request_once import (
    HttpErrorPayload,
    HttpOutcome,
    HttpResponsePayload,
    request_once,
)

__all__ = [
    "HttpClientSettings",
    "build_http_client",
    "HttpErrorPayload",
    "HttpOutcome",
    "HttpResponsePayload",
    "HttpNormalizedOutcome",
    "HttpOperationDataModel",
    "HttpRequest",
    "compile_http_operation",
    "build_http_request",
    "compile_http_operation_data",
    "normalize_http_outcome",
    "request_once",
]
