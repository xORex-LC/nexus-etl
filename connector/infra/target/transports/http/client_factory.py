"""Фабрика общей конфигурации `httpx.Client` для HTTP-транспорта target."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import httpx


HttpEventHooks = dict[str, list[Callable[..., Any]]]


@dataclass(frozen=True, slots=True)
class HttpClientSettings:
    """Параметры сборки `httpx.Client`."""

    base_url: str
    timeout_seconds: float = 20.0
    connect_timeout_seconds: float | None = None
    read_timeout_seconds: float | None = None
    write_timeout_seconds: float | None = None
    pool_timeout_seconds: float | None = None
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry_seconds: float | None = 5.0
    tls_skip_verify: bool = False
    ca_file: str | None = None
    transport: httpx.BaseTransport | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    event_hooks: HttpEventHooks | None = None
    auth: httpx.Auth | None = None
    proxy: str | None = None


def build_http_client(settings: HttpClientSettings) -> httpx.Client:
    """Собрать настроенный `httpx.Client` для транспорта с одной попыткой I/O."""
    verify: bool | str = True
    if settings.tls_skip_verify:
        verify = False
    elif settings.ca_file:
        verify = settings.ca_file

    default_timeout = settings.timeout_seconds
    timeout = httpx.Timeout(
        default_timeout,
        connect=settings.connect_timeout_seconds or default_timeout,
        read=settings.read_timeout_seconds or default_timeout,
        write=settings.write_timeout_seconds or default_timeout,
        pool=settings.pool_timeout_seconds or default_timeout,
    )
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
        keepalive_expiry=settings.keepalive_expiry_seconds,
    )
    return httpx.Client(
        base_url=settings.base_url.rstrip("/"),
        timeout=timeout,
        verify=verify,
        limits=limits,
        transport=settings.transport,
        headers=dict(settings.default_headers),
        event_hooks=settings.event_hooks,
        auth=settings.auth,
        proxy=settings.proxy,
    )


__all__ = ["HttpClientSettings", "build_http_client"]
