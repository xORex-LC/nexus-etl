from __future__ import annotations

import pytest

from connector.config.app_settings import ApiSettings
from connector.infra.target.core.factory import (
    build_target_runtime,
    build_target_runtime_with_info,
)
from connector.infra.target.providers.ankey_rest.provider import apply_retry_overrides
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec


@pytest.fixture()
def api_settings() -> ApiSettings:
    return ApiSettings(
        host="ankey.local",
        port=9443,
        username="svc",
        password="secret",
        tls_skip_verify=False,
        ca_file=None,
        timeout_seconds=10.0,
        retries=7,
        retry_backoff_seconds=1.25,
        resource_exists_retries=3,
    )


def test_build_target_runtime_returns_runtime_with_typed_meta(api_settings: ApiSettings) -> None:
    runtime = build_target_runtime(api_settings, include_reader=False)

    meta = runtime.meta()
    assert meta.target_type == "ankey"
    assert meta.base_url == "https://ankey.local:9443"
    assert meta.transport == "http"
    assert runtime.reader is None
    assert runtime.executor is not None


def test_build_target_runtime_applies_retry_overrides(api_settings: ApiSettings) -> None:
    runtime = build_target_runtime(
        api_settings,
        include_reader=False,
        runtime_mode="core",
    )
    gateway = runtime.executor  # type: ignore[assignment]
    spec = gateway._kernel.spec  # type: ignore[attr-defined]

    assert spec.retry_config.max_attempts == 7
    assert spec.retry_config.backoff_base == 1.25


def test_build_target_runtime_loads_operation_catalog(api_settings: ApiSettings) -> None:
    runtime = build_target_runtime(
        api_settings,
        include_reader=False,
        runtime_mode="core",
    )
    gateway = runtime.executor  # type: ignore[assignment]
    operation = gateway._kernel.resolve_operation("users.upsert")  # type: ignore[attr-defined]
    list_operation = gateway._kernel.resolve_operation("users.list")  # type: ignore[attr-defined]
    health_operation = gateway._kernel.resolve_operation("health.check")  # type: ignore[attr-defined]

    assert operation.alias == "users.upsert"
    assert operation.http is not None
    assert operation.http.path_template == "/ankey/managed/user/{target_id}"
    assert list_operation.http is not None
    assert list_operation.http.path_template == "/ankey/managed/user"
    assert health_operation.http is not None
    assert health_operation.http.path_template == "/ankey/managed/user"


def test_apply_retry_overrides_is_immutable(api_settings: ApiSettings) -> None:
    original = build_ankey_spec()
    updated = apply_retry_overrides(original, api_settings)

    assert updated is not original
    assert original.retry_config.max_attempts == 3
    assert original.retry_config.backoff_base == 0.5
    assert updated.retry_config.max_attempts == api_settings.retries
    assert updated.retry_config.backoff_base == api_settings.retry_backoff_seconds


def test_build_target_runtime_sets_single_attempt_client_and_injects_transport(
    monkeypatch: pytest.MonkeyPatch,
    api_settings: ApiSettings,
) -> None:
    captured: dict[str, object] = {}
    transport = object()

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import connector.infra.target.providers.ankey_rest.provider as provider_mod

    monkeypatch.setattr(provider_mod, "AnkeyApiClient", FakeClient)

    runtime = build_target_runtime(
        api_settings,
        include_reader=False,
        transport=transport,
        runtime_mode="core",
    )

    assert runtime.meta().base_url == "https://ankey.local:9443"
    assert captured["retries"] == 0
    assert captured["retryBackoffSeconds"] == 0
    assert captured["transport"] is transport


def test_build_target_runtime_with_info_reports_core_mode(
    api_settings: ApiSettings,
) -> None:
    build = build_target_runtime_with_info(
        api_settings,
        include_reader=False,
    )

    assert build.requested_mode == "core"
    assert build.effective_mode == "core"


def test_build_target_runtime_rejects_invalid_mode(api_settings: ApiSettings) -> None:
    with pytest.raises(ValueError):
        build_target_runtime(api_settings, include_reader=False, runtime_mode="broken")

    with pytest.raises(ValueError):
        build_target_runtime(api_settings, include_reader=False, runtime_mode="legacy")

    with pytest.raises(ValueError):
        build_target_runtime(api_settings, include_reader=False, runtime_mode="auto")
