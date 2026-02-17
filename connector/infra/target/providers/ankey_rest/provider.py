"""Провайдер target для Ankey (wiring только через core runtime)."""

from __future__ import annotations

from connector.config.app_settings import ApiSettings
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.models import TargetConnectionConfig
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime
from connector.infra.target.core.spec_models import TargetSpec
from connector.infra.target.core.transport_compiler import TransportCompilerRegistry
from connector.infra.target.providers.ankey_rest.auth import AnkeyAuth
from connector.infra.target.providers.ankey_rest.driver import AnkeyHttpDriver
from connector.infra.target.providers.ankey_rest.mutations import build_ankey_mutations
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec
from connector.infra.target.transports.http.compiler import compile_http_operation
from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)


def apply_retry_overrides(
    spec: TargetSpec,
    api_settings: ApiSettings,
) -> TargetSpec:
    """Применить runtime-настройки retry поверх дефолтной спецификации провайдера."""
    new_retry_config = spec.retry_config.model_copy(
        update={
            "max_attempts": api_settings.retries,
            "backoff_base": api_settings.retry_backoff_seconds,
        },
    )
    return spec.model_copy(update={"retry_config": new_retry_config})


def build_transport_compiler_registry() -> TransportCompilerRegistry:
    """Собрать реестр компиляторов transport-операций для Ankey runtime."""
    registry = TransportCompilerRegistry()
    registry.register("http", compile_http_operation)
    return registry


class AnkeyTargetProvider:
    target_type = "ankey"

    def __init__(self, api_settings: ApiSettings) -> None:
        self._api_settings = api_settings

    def build_core_runtime(
        self,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime:
        api = self._api_settings
        base_url = f"https://{api.host}:{api.port}"

        spec = build_ankey_spec()
        spec = apply_retry_overrides(spec, api)
        kernel = TargetKernel(
            spec,
            compiler_registry=build_transport_compiler_registry(),
        )

        client = build_http_client(
            HttpClientSettings(
                base_url=base_url,
                timeout_seconds=api.timeout_seconds,
                tls_skip_verify=api.tls_skip_verify,
                ca_file=api.ca_file,
                transport=transport,
                auth=AnkeyAuth(
                    username=api.username or "",
                    password=api.password or "",
                ),
            )
        )

        driver = AnkeyHttpDriver(client)
        gateway = TargetGateway(
            driver,
            kernel,
            mutation_registry=TargetMutationRegistry(build_ankey_mutations()),
        )
        config = TargetConnectionConfig(
            target_type=self.target_type,
            endpoint=base_url,
            transport="http",
            principal=api.username or "",
        )
        return DefaultTargetRuntime(
            gateway=gateway,
            config=config,
            has_reader=include_reader,
        )


__all__ = [
    "AnkeyTargetProvider",
    "apply_retry_overrides",
    "build_transport_compiler_registry",
]
