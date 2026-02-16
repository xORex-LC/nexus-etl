from __future__ import annotations

import pytest

from connector.config.app_settings import ApiSettings
from connector.infra.target.factory import (
    build_target_runtime,
    build_target_runtime_with_info,
)
from connector.infra.target.providers.ankey import apply_retry_overrides
from connector.infra.target.spec_ankey import build_ankey_spec


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
        target_runtime_mode="auto",
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


def test_build_target_runtime_legacy_mode_uses_api_retry_settings(
    monkeypatch: pytest.MonkeyPatch,
    api_settings: ApiSettings,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def getJson(self, *_args, **_kwargs):  # noqa: N802
            return {"items": []}

        def getRetryAttempts(self) -> int:  # noqa: N802
            return 0

        def resetRetryAttempts(self) -> None:  # noqa: N802
            return None

    import connector.infra.target.legacy.runtime as legacy_runtime_mod

    monkeypatch.setattr(legacy_runtime_mod, "AnkeyApiClient", FakeClient)

    _ = build_target_runtime(
        api_settings,
        include_reader=False,
        runtime_mode="legacy",
    )

    assert captured["retries"] == api_settings.retries
    assert captured["retryBackoffSeconds"] == api_settings.retry_backoff_seconds


def test_build_target_runtime_auto_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
    api_settings: ApiSettings,
) -> None:
    class StubRuntime:
        @property
        def executor(self):  # pragma: no cover - not used in this test
            return object()

        @property
        def reader(self):  # pragma: no cover - not used in this test
            return None

        def check(self):
            raise NotImplementedError

        def meta(self):
            class _Meta:
                target_type = "ankey"
                base_url = "https://stub"
                transport = "http"

            return _Meta()

        def stats(self):
            class _Stats:
                requests_total = 0
                retries_total = 0
                failures_total = 0

            return _Stats()

        def reset(self) -> None:
            return None

    class FakeProvider:
        target_type = "ankey"

        def build_core_runtime(self, *_args, **_kwargs):
            raise RuntimeError("core bootstrap failed")

        def build_legacy_runtime(self, *_args, **_kwargs):
            return StubRuntime()

    import connector.infra.target.core.factory as factory_mod

    monkeypatch.setattr(factory_mod, "_get_default_provider", lambda: FakeProvider())

    build = build_target_runtime_with_info(
        api_settings,
        include_reader=False,
        runtime_mode="auto",
    )

    assert build.requested_mode == "auto"
    assert build.effective_mode == "legacy"
    assert build.fallback_reason is not None
    assert "core bootstrap failed" in build.fallback_reason


def test_build_target_runtime_rejects_invalid_mode(api_settings: ApiSettings) -> None:
    with pytest.raises(ValueError):
        build_target_runtime(api_settings, include_reader=False, runtime_mode="broken")
