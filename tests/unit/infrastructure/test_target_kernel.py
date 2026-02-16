"""
Unit-тесты для TargetKernel.

Проверяет: classify_fault, retry_directive, system_error_code,
redact_headers, redact_payload, safe_body.
"""

from __future__ import annotations

import pytest

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.spec_models import RedactionSpec
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec


@pytest.fixture()
def kernel() -> TargetKernel:
    return TargetKernel(build_ankey_spec())


# ---------------------------------------------------------------------------
# Проверка classify_fault
# ---------------------------------------------------------------------------


class TestClassifyFault:
    def test_401_returns_auth(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=401) == "AUTH"

    def test_403_returns_permission(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=403) == "PERMISSION"

    def test_400_returns_data(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=400) == "DATA"

    def test_422_returns_data(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=422) == "DATA"

    def test_404_returns_not_found(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=404) == "NOT_FOUND"

    def test_409_returns_conflict(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=409) == "CONFLICT"

    def test_429_returns_throttle(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=429) == "THROTTLE"

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
    def test_5xx_returns_transient(self, kernel: TargetKernel, status: int) -> None:
        assert kernel.classify_fault(status_code=status) == "TRANSIENT"

    def test_network_error_returns_transient(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(error_code="NETWORK_ERROR") == "TRANSIENT"

    def test_unknown_status_returns_unknown(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault(status_code=418) == "UNKNOWN"

    def test_no_args_returns_unknown(self, kernel: TargetKernel) -> None:
        assert kernel.classify_fault() == "UNKNOWN"

    def test_error_code_takes_priority_over_status(self, kernel: TargetKernel) -> None:
        result = kernel.classify_fault(status_code=401, error_code="NETWORK_ERROR")
        assert result == "TRANSIENT"


# ---------------------------------------------------------------------------
# Проверка retry_directive
# ---------------------------------------------------------------------------


class TestRetryDirective:
    def test_transient_gets_retry_backoff(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("TRANSIENT") == "RETRY_BACKOFF"

    def test_throttle_gets_retry_backoff(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("THROTTLE") == "RETRY_BACKOFF"

    def test_auth_gets_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("AUTH") == "NO_RETRY"

    def test_permission_gets_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("PERMISSION") == "NO_RETRY"

    def test_data_gets_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("DATA") == "NO_RETRY"

    def test_not_found_gets_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("NOT_FOUND") == "NO_RETRY"

    def test_conflict_gets_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("CONFLICT") == "NO_RETRY"

    def test_unknown_defaults_to_no_retry(self, kernel: TargetKernel) -> None:
        assert kernel.retry_directive("UNKNOWN") == "NO_RETRY"

    def test_conflict_resourceexists_resolves_mutation_retry(self, kernel: TargetKernel) -> None:
        action = kernel.resolve_retry_action(
            fault_kind="CONFLICT",
            status_code=409,
            error_reason="resourceexists",
        )

        assert action.directive == "RETRY_BACKOFF"
        assert action.mutation == "regenerate_target_id"

    def test_conflict_without_reason_stays_no_retry(self, kernel: TargetKernel) -> None:
        action = kernel.resolve_retry_action(
            fault_kind="CONFLICT",
            status_code=409,
            error_reason=None,
        )

        assert action.directive == "NO_RETRY"
        assert action.mutation is None


# ---------------------------------------------------------------------------
# Проверка system_error_code
# ---------------------------------------------------------------------------


class TestSystemErrorCode:
    def test_auth_maps_to_unauthorized(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("AUTH") == SystemErrorCode.AUTH_UNAUTHORIZED

    def test_permission_maps_to_forbidden(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("PERMISSION") == SystemErrorCode.AUTH_FORBIDDEN

    def test_data_maps_to_data_invalid(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("DATA") == SystemErrorCode.DATA_INVALID

    def test_conflict_maps_to_conflict(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("CONFLICT") == SystemErrorCode.CONFLICT

    def test_transient_maps_to_unavailable(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("TRANSIENT") == SystemErrorCode.INFRA_UNAVAILABLE

    def test_unknown_maps_to_internal(self, kernel: TargetKernel) -> None:
        assert kernel.system_error_code("UNKNOWN") == SystemErrorCode.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# Проверка redact_headers
# ---------------------------------------------------------------------------


class TestRedactHeaders:
    def test_masks_authorization(self, kernel: TargetKernel) -> None:
        result = kernel.redact_headers({"Authorization": "Bearer token123"})
        assert result == {"Authorization": "***"}

    def test_masks_x_ankey_password(self, kernel: TargetKernel) -> None:
        result = kernel.redact_headers({"X-Ankey-Password": "secret"})
        assert result == {"X-Ankey-Password": "***"}

    def test_preserves_safe_headers(self, kernel: TargetKernel) -> None:
        headers = {"Content-Type": "application/json", "Accept": "text/html"}
        result = kernel.redact_headers(headers)
        assert result == headers

    def test_mixed_headers(self, kernel: TargetKernel) -> None:
        result = kernel.redact_headers({
            "Content-Type": "application/json",
            "Authorization": "Basic abc",
            "X-Api-Key": "key123",
        })
        assert result["Content-Type"] == "application/json"
        assert result["Authorization"] == "***"
        assert result["X-Api-Key"] == "***"


# ---------------------------------------------------------------------------
# Проверка redact_payload
# ---------------------------------------------------------------------------


class TestRedactPayload:
    def test_masks_password_field(self, kernel: TargetKernel) -> None:
        result = kernel.redact_payload({"username": "admin", "password": "secret"})
        assert result["username"] == "admin"
        assert result["password"] == "***"

    def test_non_dict_returns_as_is(self, kernel: TargetKernel) -> None:
        assert kernel.redact_payload("plain text") == "plain text"
        assert kernel.redact_payload(42) == 42


# ---------------------------------------------------------------------------
# Проверка safe_body
# ---------------------------------------------------------------------------


class TestSafeBody:
    def test_none_mode_returns_none(self, kernel: TargetKernel) -> None:
        spec = RedactionSpec(body_mode="none")
        assert kernel.safe_body({"key": "val"}, redaction=spec) is None

    def test_keys_only_mode_returns_keys(self, kernel: TargetKernel) -> None:
        spec = RedactionSpec(body_mode="keys_only")
        result = kernel.safe_body({"name": "John", "password": "x"}, redaction=spec)
        assert sorted(result) == ["name", "password"]

    def test_truncated_mode_masks_secrets(self, kernel: TargetKernel) -> None:
        result = kernel.safe_body({"name": "John", "password": "x"})
        assert result["name"] == "John"
        assert result["password"] == "***"


# ---------------------------------------------------------------------------
# Проверка свойства spec
# ---------------------------------------------------------------------------


def test_spec_property_returns_original(kernel: TargetKernel) -> None:
    spec = build_ankey_spec()
    k = TargetKernel(spec)
    assert k.spec is spec


# ---------------------------------------------------------------------------
# Проверка алиасов операций
# ---------------------------------------------------------------------------


def test_resolve_operation_returns_operation_spec(kernel: TargetKernel) -> None:
    operation = kernel.resolve_operation("users.upsert")
    assert operation.alias == "users.upsert"
    assert operation.kind == "http"
    assert operation.data["method"] == "PUT"


def test_resolve_operation_unknown_alias_raises(kernel: TargetKernel) -> None:
    with pytest.raises(ValueError, match="unknown operation alias"):
        kernel.resolve_operation("users.unknown")


def test_build_http_operation_renders_path_and_merges_defaults(kernel: TargetKernel) -> None:
    request = kernel.build_http_operation(
        "users.upsert",
        operation_params={"target_id": "abc-123"},
        query_overrides={"decrypt": "true"},
    )

    assert request.method == "PUT"
    assert request.path == "/ankey/managed/user/abc-123"
    assert request.expected_statuses == (200, 201)
    assert request.query == {"_prettyPrint": "true", "decrypt": "true"}


def test_build_http_operation_requires_path_params(kernel: TargetKernel) -> None:
    with pytest.raises(ValueError, match="missing path params"):
        kernel.build_http_operation("users.upsert")
