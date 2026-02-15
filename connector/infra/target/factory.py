"""
Фабрика TargetRuntime — единая точка сборки target-инфраструктуры.

Назначение:
    Собирает TargetRuntime из ApiSettings, скрывая конкретные infra-реализации
    (AnkeyApiClient, AnkeyRequestExecutor, AnkeyTargetPagedReader) от delivery.
"""

from __future__ import annotations

from dataclasses import replace

from connector.config.app_settings import ApiSettings
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.target.driver import AnkeyHttpDriver
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.models import TargetConnectionConfig
from connector.infra.target.runtime import DefaultTargetRuntime, TargetRuntime
from connector.infra.target.spec import TargetSpec
from connector.infra.target.spec_ankey import build_ankey_spec


def build_target_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
) -> TargetRuntime:
    """
    Назначение:
        Единая фабрика TargetRuntime для production.

    Контракт:
        - AnkeyApiClient создаётся с retries=0 (single attempt).
        - Retry-политика управляется TargetGateway через TargetSpec.
        - RetryConfig переопределяется из api_settings (retries, backoff).
        - transport: опциональный httpx.BaseTransport для тестовой инъекции.
    """
    base_url = f"https://{api_settings.host}:{api_settings.port}"

    spec = build_ankey_spec()
    spec = _apply_settings_overrides(spec, api_settings)

    kernel = TargetKernel(spec)

    client = AnkeyApiClient(
        baseUrl=base_url,
        username=api_settings.username or "",
        password=api_settings.password or "",
        timeoutSeconds=api_settings.timeout_seconds,
        tlsSkipVerify=api_settings.tls_skip_verify,
        caFile=api_settings.ca_file,
        retries=0,
        retryBackoffSeconds=0,
        transport=transport,
    )

    driver = AnkeyHttpDriver(client)
    gateway = TargetGateway(driver, kernel)

    config = TargetConnectionConfig(
        target_type="ankey",
        base_url=base_url,
        username=api_settings.username or "",
    )

    return DefaultTargetRuntime(
        gateway=gateway,
        config=config,
        has_reader=include_reader,
    )


def _apply_settings_overrides(
    spec: TargetSpec, api_settings: ApiSettings
) -> TargetSpec:
    """Переопределить RetryConfig из app settings."""
    new_retry_config = replace(
        spec.retry_config,
        max_attempts=api_settings.retries,
        backoff_base=api_settings.retry_backoff_seconds,
    )
    return replace(spec, retry_config=new_retry_config)
