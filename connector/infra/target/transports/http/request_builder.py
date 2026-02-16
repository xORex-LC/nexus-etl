"""Сборка HTTP-запроса из operation data и runtime-параметров."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from connector.infra.target.transports.http.op_models import HttpOperationDataModel

_PATH_TEMPLATE_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    path: str
    query: dict[str, Any]
    headers: dict[str, str]
    json: Any | None = None
    timeout_s: float | None = None


def _render_path_template(
    *,
    alias: str,
    path_template: str,
    params: dict[str, Any] | None,
) -> str:
    params = params or {}
    required = _PATH_TEMPLATE_PARAM_RE.findall(path_template)
    missing = [name for name in required if name not in params]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"operation {alias!r} missing path params: {joined}")
    try:
        return path_template.format(**params)
    except KeyError as exc:
        raise ValueError(f"operation {alias!r} missing path param: {exc}") from exc


def build_http_request(
    *,
    alias: str,
    op_data: HttpOperationDataModel,
    operation_params: dict[str, Any] | None = None,
    query_overrides: dict[str, Any] | None = None,
    header_overrides: dict[str, str] | None = None,
) -> HttpRequest:
    """Собрать транспортный HTTP-запрос (без исполнения)."""
    path = _render_path_template(
        alias=alias,
        path_template=op_data.path_template,
        params=operation_params,
    )
    query = dict(op_data.query_defaults)
    if query_overrides:
        query.update(query_overrides)
    headers = dict(op_data.header_defaults)
    if header_overrides:
        headers.update(header_overrides)
    return HttpRequest(
        method=op_data.method,
        path=path,
        query=query,
        headers=headers,
    )
