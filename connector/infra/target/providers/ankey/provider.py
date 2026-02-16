from __future__ import annotations

from dataclasses import replace

from connector.config.app_settings import ApiSettings
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.target.core.provider import TargetProvider
from connector.infra.target.driver import AnkeyHttpDriver
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.legacy.runtime import build_legacy_ankey_runtime
from connector.infra.target.models import TargetConnectionConfig
from connector.infra.target.runtime import DefaultTargetRuntime, TargetRuntime
from connector.infra.target.spec import TargetSpec
from connector.infra.target.spec_ankey import build_ankey_spec


def apply_retry_overrides(
    spec: TargetSpec,
    api_settings: ApiSettings,
) -> TargetSpec:
    """Apply runtime retry settings on top of provider default spec."""
    new_retry_config = replace(
        spec.retry_config,
        max_attempts=api_settings.retries,
        backoff_base=api_settings.retry_backoff_seconds,
    )
    return replace(spec, retry_config=new_retry_config)


class AnkeyTargetProvider(TargetProvider):
    target_type = "ankey"

    def build_core_runtime(
        self,
        api_settings: ApiSettings,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime:
        base_url = f"https://{api_settings.host}:{api_settings.port}"

        spec = build_ankey_spec()
        spec = apply_retry_overrides(spec, api_settings)
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
            target_type=self.target_type,
            base_url=base_url,
            username=api_settings.username or "",
        )
        return DefaultTargetRuntime(
            gateway=gateway,
            config=config,
            has_reader=include_reader,
        )

    def build_legacy_runtime(
        self,
        api_settings: ApiSettings,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime:
        return build_legacy_ankey_runtime(
            api_settings,
            transport=transport,
            include_reader=include_reader,
        )
