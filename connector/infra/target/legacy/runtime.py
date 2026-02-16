from __future__ import annotations

import time

from connector.config.app_settings import ApiSettings
from connector.domain.diagnostics.policies import SystemErrorCode, map_http_status
from connector.domain.ports.target.execution import RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPagedReaderProtocol
from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.target.ankey_gateway import AnkeyTargetPagedReader
from connector.infra.target.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetMeta,
    TargetStats,
)
from connector.infra.target.runtime import TargetRuntime


class LegacyAnkeyRuntime(TargetRuntime):
    """Legacy runtime adapter based on pre-target-core API components."""

    def __init__(
        self,
        *,
        client: AnkeyApiClient,
        config: TargetConnectionConfig,
        include_reader: bool = True,
    ) -> None:
        self._client = client
        self._config = config
        self._executor = AnkeyRequestExecutor(client)
        self._reader = AnkeyTargetPagedReader(client) if include_reader else None

    @property
    def executor(self) -> RequestExecutorProtocol:
        return self._executor

    @property
    def reader(self) -> TargetPagedReaderProtocol | None:
        return self._reader

    def check(self) -> TargetCheckResult:
        start = time.monotonic()
        try:
            self._client.getJson("/ankey/managed/user", {"page": 1, "rows": 1, "_queryFilter": "true"})  # noqa: N802
            latency_ms = int((time.monotonic() - start) * 1000)
            return TargetCheckResult(ok=True, latency_ms=latency_ms)
        except ApiError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            if exc.code == "NETWORK_ERROR":
                error_code = SystemErrorCode.INFRA_UNAVAILABLE
            elif exc.status_code is not None:
                error_code = map_http_status(exc.status_code)
            else:
                error_code = SystemErrorCode.INTERNAL_ERROR
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive
            latency_ms = int((time.monotonic() - start) * 1000)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                error_code=SystemErrorCode.INFRA_UNAVAILABLE,
                error_message=str(exc),
            )

    def meta(self) -> TargetMeta:
        return TargetMeta(
            target_type=self._config.target_type,
            base_url=self._config.base_url,
            transport=self._config.transport,
        )

    def stats(self) -> TargetStats:
        retries = self._client.getRetryAttempts()
        return TargetStats(requests_total=0, retries_total=retries, failures_total=0)

    def reset(self) -> None:
        self._client.resetRetryAttempts()


def build_legacy_ankey_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
) -> TargetRuntime:
    base_url = f"https://{api_settings.host}:{api_settings.port}"
    client = AnkeyApiClient(
        baseUrl=base_url,
        username=api_settings.username or "",
        password=api_settings.password or "",
        timeoutSeconds=api_settings.timeout_seconds,
        tlsSkipVerify=api_settings.tls_skip_verify,
        caFile=api_settings.ca_file,
        retries=api_settings.retries,
        retryBackoffSeconds=api_settings.retry_backoff_seconds,
        transport=transport,
    )
    config = TargetConnectionConfig(
        target_type="ankey",
        base_url=base_url,
        username=api_settings.username or "",
    )
    return LegacyAnkeyRuntime(
        client=client,
        config=config,
        include_reader=include_reader,
    )
