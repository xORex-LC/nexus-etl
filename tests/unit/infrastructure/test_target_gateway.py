from __future__ import annotations

from typing import Any, Iterator

import pytest

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.core.spec_models import RetryRule
from connector.infra.target.driver import DriverError, DriverResponse
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.providers.ankey_rest.mutations import build_ankey_mutations
from connector.infra.target.providers.ankey_rest.provider import build_transport_compiler_registry
from connector.domain.target_dsl import load_target_spec


class StubDriver:
    def __init__(
        self,
        *,
        request_effects: list[DriverResponse | Exception] | None = None,
        pages_effect: list[tuple[int, list[Any]]] | Exception | None = None,
    ) -> None:
        self._execute_effects = list(request_effects or [])
        self._pages_effect = pages_effect
        self.request_calls: list[dict[str, Any]] = []

    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        self.request_calls.append(
            {
                "method": compiled_request.method,
                "path": compiled_request.path,
                "params": compiled_request.query,
                "json": payload,
                "headers": compiled_request.headers,
            }
        )
        if not self._execute_effects:
            return DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None)
        effect = self._execute_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        if isinstance(self._pages_effect, Exception):
            raise self._pages_effect
        for page in self._pages_effect or []:
            yield page

    def close(self) -> None:
        pass


def _make_gateway(
    *,
    driver: StubDriver,
    max_attempts: int = 3,
    backoff_base: float = 0.0,
    spec_updates: dict[str, Any] | None = None,
) -> TargetGateway:
    spec = load_target_spec("ankey")
    update_payload: dict[str, Any] = {
        "retry_config": spec.retry_config.model_copy(
            update={
                "max_attempts": max_attempts,
                "backoff_base": backoff_base,
                "backoff_max": backoff_base,
                "jitter": False,
            },
        )
    }
    if spec_updates:
        update_payload.update(spec_updates)
    spec = spec.model_copy(
        update=update_payload,
    )
    kernel = TargetKernel(
        spec,
        compiler_registry=build_transport_compiler_registry(),
    )
    return TargetGateway(
        driver,
        kernel,
        mutation_registry=TargetMutationRegistry(build_ankey_mutations()),
    )  # type: ignore[arg-type]


def _upsert_spec(*, target_id: str = "target-001") -> RequestSpec:
    return RequestSpec.operation(
        alias="users.upsert",
        params={"target_id": target_id},
        payload={"name": "Alice"},
    )


def test_execute_happy_path_returns_ok_and_masks_response() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                ok=True,
                answer_code=200,
                payload={"name": "Alice", "password": "secret"},
                content_preview=None,
            )
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = _upsert_spec()

    result = gateway.execute(spec)

    assert result.ok is True
    assert result.answer_code == 200
    assert result.response_payload == {"name": "Alice", "password": "***"}
    assert gateway.get_stats() == (1, 0, 0)


def test_execute_retries_on_transient_and_then_succeeds() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=False, answer_code=503, payload={"error": "temporary"}, content_preview="temporary"),
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=2)
    spec = _upsert_spec()

    result = gateway.execute(spec)

    assert result.ok is True
    assert result.answer_code == 200
    assert gateway.get_stats() == (2, 1, 0)


def test_execute_no_retry_on_auth_error() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=False, answer_code=401, payload={"message": "unauthorized"}, content_preview="unauthorized")
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = _upsert_spec()

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.answer_code == 401
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
    spec = _upsert_spec()

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.answer_code is None
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert gateway.get_stats() == (3, 2, 1)


def test_execute_detects_resourceexists_reason() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                ok=False,
                answer_code=409,
                payload={"message": "resourceexists"},
                content_preview="resource exists",
                error_reason="resourceexists",
            )
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=0)
    spec = _upsert_spec()

    result = gateway.execute(spec)

    assert result.ok is False
    assert result.error_code == SystemErrorCode.CONFLICT
    assert result.error_reason == "resourceexists"


def test_execute_operation_alias_applies_resourceexists_mutation_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import connector.infra.target.providers.ankey_rest.mutations as mutation_mod

    monkeypatch.setattr(mutation_mod.uuid, "uuid4", lambda: "regen-123")
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                ok=False,
                answer_code=409,
                payload={"message": "resourceexists"},
                content_preview="resource exists",
                error_reason="resourceexists",
            ),
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=2)
    spec = RequestSpec.operation(
        alias="users.upsert",
        params={"target_id": "orig-001"},
        payload={"name": "Alice"},
    )

    result = gateway.execute(spec)

    assert result.ok is True
    assert len(driver.request_calls) == 2
    assert driver.request_calls[0]["path"] == "/ankey/managed/user/orig-001"
    assert driver.request_calls[1]["path"] == "/ankey/managed/user/regen-123"


def test_execute_retries_on_retry_after_directive() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(
                ok=False,
                answer_code=429,
                payload={"error": "throttle"},
                content_preview="throttle",
                retry_after_s=0.0,
            ),
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ]
    )
    gateway = _make_gateway(driver=driver, max_attempts=1)

    result = gateway.execute(_upsert_spec())

    assert result.ok is True
    assert gateway.get_stats() == (2, 1, 0)


def test_execute_escalate_stops_retry_cycle() -> None:
    driver = StubDriver(
        request_effects=[
            DriverError("network down"),
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ]
    )
    gateway = _make_gateway(
        driver=driver,
        max_attempts=3,
        spec_updates={
            "retry_rules": (
                RetryRule(directive="ESCALATE", match_fault="TRANSIENT"),
            ),
        },
    )

    result = gateway.execute(_upsert_spec())

    assert result.ok is False
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert result.error_details is not None
    assert result.error_details.get("escalated") is True
    assert gateway.get_stats() == (1, 0, 1)


def test_execute_operation_alias_uses_spec_mapping() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
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
    assert result.answer_code is None
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


def test_request_spec_rejects_empty_alias() -> None:
    with pytest.raises(ValueError, match="operation_alias must not be empty"):
        RequestSpec.operation(alias="   ")


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


def test_iter_pages_normalizes_driver_error_and_sanitizes_details() -> None:
    driver_error = DriverError(
        "HTTP 500",
        code="HTTP_500",
        answer_code=500,
        content_preview="x" * 600,
        details={"password": "very-secret"},
    )
    driver = StubDriver(pages_effect=driver_error)
    gateway = _make_gateway(driver=driver)

    results = list(gateway.iter_pages("users.list", page_size=100, max_pages=2))

    assert len(results) == 1
    fail = results[0]
    assert fail.ok is False
    assert fail.error_code == SystemErrorCode.INFRA_UNAVAILABLE
    assert fail.error_details is not None
    assert fail.error_details["password"] == "***"
    snippet = fail.error_details["content_preview"]
    assert isinstance(snippet, str)
    assert len(snippet) <= 500
    assert snippet.endswith("...")


def test_health_check_ok() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
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


def test_health_check_uses_operation_catalog_alias() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ],
    )
    gateway = _make_gateway(driver=driver)

    result = gateway.health_check()

    assert result.ok is True
    assert len(driver.request_calls) == 1
    assert driver.request_calls[0]["path"] == "/ankey/managed/user"


def test_reset_stats_resets_all_counters() -> None:
    driver = StubDriver(
        request_effects=[
            DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None),
        ]
    )
    gateway = _make_gateway(driver=driver)
    spec = _upsert_spec()
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
