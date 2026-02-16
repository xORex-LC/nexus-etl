from __future__ import annotations

from typing import Any, Iterable, Iterator

import pytest

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import RequestSpec
from connector.infra.http.ankey_client import ApiError
from connector.infra.target.driver import DriverError, DriverResponse
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.spec_ankey import build_ankey_spec


class StubDriver:
    def __init__(
        self,
        *,
        request_effects: list[DriverResponse | Exception] | None = None,
        get_json_effect: Any = None,
        pages_effect: Iterable[tuple[int, list[Any]]] | Exception | None = None,
    ) -> None:
        self._request_effects = list(request_effects or [])
        self._get_json_effect = get_json_effect
        self._pages_effect = pages_effect
        self.request_calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse:
        self.request_calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        if not self._request_effects:
            return DriverResponse(status_code=200, body={"ok": True}, body_snippet=None)
        effect = self._request_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if isinstance(self._get_json_effect, Exception):
            raise self._get_json_effect
        return self._get_json_effect

    def get_paged_items(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        if isinstance(self._pages_effect, Exception):
            raise self._pages_effect
        for page in self._pages_effect or []:
            yield page


def _make_gateway(
    *,
    driver: StubDriver,
    max_attempts: int = 3,
    backoff_base: float = 0.0,
) -> TargetGateway:
    spec = build_ankey_spec()
    spec = spec.model_copy(
        update={
            "retry_config": spec.retry_config.model_copy(
                update={
                    "max_attempts": max_attempts,
                    "backoff_base": backoff_base,
                    "backoff_max": backoff_base,
                    "jitter": False,
                },
            )
        },
    )
    kernel = TargetKernel(spec)
    return TargetGateway(driver, kernel)  # type: ignore[arg-type]


def test_execute_happy_path_returns_ok_and_masks_response() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                status_code=200,
                body={"name": "Alice", "password": "secret"},
                body_snippet=None,
            )
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))

    result = gateway.execute(spec)

    assert result.ok is True
    assert result.status_code == 200
    assert result.response_json == {"name": "Alice", "password": "***"}
    assert gateway.get_stats() == (1, 0, 0)


def test_execute_retries_on_transient_and_then_succeeds() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=503, body={"error": "temporary"}, body_snippet="temporary"),
            DriverResponse(status_code=200, body={"ok": True}, body_snippet=None),
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=2)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))

    result = gateway.execute(spec)

    assert result.ok is True
    assert result.status_code == 200
    assert gateway.get_stats() == (2, 1, 0)


def test_execute_no_retry_on_auth_error() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=401, body={"message": "unauthorized"}, body_snippet="unauthorized")
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.status_code == 401
    assert result.error_code == SystemErrorCode.AUTH_UNAUTHORIZED
    assert gateway.get_stats() == (1, 0, 1)


def test_execute_retries_on_driver_error_and_exhausts() -> None:
    driver = StubDriver(
        request_effects=[
            DriverError("network down"),
            DriverError("network down"),
            DriverError("network down"),
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=2)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.status_code is None
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert gateway.get_stats() == (3, 2, 1)


def test_execute_detects_resourceexists_reason() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                status_code=409,
                body={"message": "resourceexists"},
                body_snippet="resource exists",
            )
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.error_code == SystemErrorCode.CONFLICT
    assert result.error_reason == "resourceexists"


def test_execute_operation_alias_uses_spec_mapping() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=200, body={"ok": True}, body_snippet=None),
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec.operation(
        alias="users.upsert",
        params={"target_id": "user-42"},
        payload={"name": "Alice"},
    )

    result = gateway.execute(spec)

    assert result.ok is True
    assert len(driver.request_calls) == 1
    assert driver.request_calls[0]["method"] == "PUT"
    assert driver.request_calls[0]["path"] == "/ankey/managed/user/user-42"
    assert driver.request_calls[0]["params"] == {
        "_prettyPrint": "true",
        "decrypt": "false",
    }


def test_execute_operation_alias_unknown_returns_spec_error() -> None:
    driver = StubDriver()
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec.operation(alias="users.missing")

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.error_code == SystemErrorCode.INTERNAL_ERROR
    assert result.status_code is None
    assert "unknown operation alias" in (result.error_message or "")
    assert len(driver.request_calls) == 0
    assert gateway.get_stats() == (0, 0, 1)


def test_execute_operation_alias_missing_param_returns_spec_error() -> None:
    driver = StubDriver()
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec.operation(alias="users.upsert")

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.error_code == SystemErrorCode.INTERNAL_ERROR
    assert "missing path params" in (result.error_message or "")
    assert len(driver.request_calls) == 0
    assert gateway.get_stats() == (0, 0, 1)


def test_request_spec_rejects_mixed_operation_and_method_path() -> None:
    with pytest.raises(ValueError, match="method/path must be omitted"):
        RequestSpec(
            method="PUT",
            path="/ankey/managed/user/1",
            expected_statuses=(200,),
            operation_alias="users.upsert",
        )


def test_iter_pages_happy_path_masks_items() -> None:
    driver = StubDriver(
        pages_effect=[
            (1, [{"id": "u1", "password": "secret"}]),
            (2, [{"id": "u2"}]),
        ]
    )
    gateway = _make_gateway(driver=driver)

    results = list(gateway.iter_pages("users.list", page_size=100, max_pages=2))

    assert len(results) == 2
    assert results[0].ok is True
    assert results[0].items == [{"id": "u1", "password": "***"}]
    assert results[1].items == [{"id": "u2"}]
    assert gateway.get_stats() == (2, 0, 0)


def test_iter_pages_normalizes_driver_error() -> None:
    driver = StubDriver(pages_effect=DriverError("network down"))
    gateway = _make_gateway(driver=driver)

    results = list(gateway.iter_pages("users.list", page_size=100, max_pages=2))

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].page == 0
    assert results[0].error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert gateway.get_stats() == (0, 3, 1)


def test_iter_pages_normalizes_api_error_and_sanitizes_details() -> None:
    api_error = ApiError(
        "HTTP 500",
        status_code=500,
        body_snippet="x" * 600,
        details={"password": "very-secret"},
        code="HTTP_500",
    )
    driver = StubDriver(pages_effect=api_error)
    gateway = _make_gateway(driver=driver)

    results = list(gateway.iter_pages("users.list", page_size=100, max_pages=2))

    assert len(results) == 1
    fail = results[0]
    assert fail.ok is False
    assert fail.error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert fail.error_details is not None
    assert fail.error_details["password"] == "***"
    snippet = fail.error_details["body_snippet"]
    assert isinstance(snippet, str)
    assert len(snippet) <= 500
    assert snippet.endswith("...")


def test_health_check_ok() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=200, body={"ok": True}, body_snippet=None),
        ]
    )
    gateway = _make_gateway(driver=driver)

    result = gateway.health_check()

    assert result.ok is True
    assert result.error_code is None
    assert result.fault_kind is None
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


def test_health_check_driver_error_maps_to_fault_and_code() -> None:
    driver = StubDriver(request_effects=[DriverError("network down")])
    gateway = _make_gateway(driver=driver)

    result = gateway.health_check()

    assert result.ok is False
    assert result.fault_kind == "TRANSIENT"
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE


def test_health_check_unexpected_error_maps_to_transient() -> None:
    driver = StubDriver(request_effects=[RuntimeError("boom")])
    gateway = _make_gateway(driver=driver)

    result = gateway.health_check()

    assert result.ok is False
    assert result.fault_kind == "TRANSIENT"
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE


def test_health_check_uses_operation_alias_not_legacy_health_path() -> None:
    spec = build_ankey_spec()
    spec = spec.model_copy(
        update={
            "health_check": spec.health_check.model_copy(
                update={"path": "/legacy/health"},
            )
        },
    )
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=200, body={"ok": True}, body_snippet=None),
        ],
    )
    gateway = TargetGateway(driver, TargetKernel(spec))  # type: ignore[arg-type]

    result = gateway.health_check()

    assert result.ok is True
    assert len(driver.request_calls) == 1
    assert driver.request_calls[0]["path"] == "/ankey/managed/user"


def test_reset_stats_resets_all_counters() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(status_code=200, body={"ok": True}, body_snippet=None),
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = RequestSpec(method="POST", path="/users", expected_statuses=(200,))
    _ = gateway.execute(spec)
    assert gateway.get_stats() == (1, 0, 0)

    gateway.reset_stats()

    assert gateway.get_stats() == (0, 0, 0)


def test_iter_pages_unknown_alias_returns_spec_error() -> None:
    driver = StubDriver()
    gateway = _make_gateway(driver=driver)

    results = list(gateway.iter_pages("users.unknown", page_size=100, max_pages=1))

    assert len(results) == 1
    fail = results[0]
    assert fail.ok is False
    assert fail.page == 0
    assert fail.error_code == SystemErrorCode.INTERNAL_ERROR
    assert "unknown operation alias" in (fail.error_message or "")
