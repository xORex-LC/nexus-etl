from __future__ import annotations

from connector.domain.error_codes import ErrorCode
from connector.domain.ports.execution import RequestSpec
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.http.ankey_client import ApiError


class DummyClient:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    def requestAny(self, **kwargs):
        self.last_kwargs = kwargs
        return 200, {"ok": True}, None


def test_executor_passes_payload_as_json_kwarg():
    client = DummyClient()
    executor = AnkeyRequestExecutor(client)
    payload = {"name": "Jane", "role": "dev"}

    result = executor.execute(RequestSpec.put("/ankey/managed/user/1", payload=payload))

    assert result.ok is True
    assert client.last_kwargs is not None
    assert client.last_kwargs.get("json") == payload
    assert "jsonBody" not in client.last_kwargs


def test_executor_sets_error_reason_from_payload():
    class ClientWithConflict:
        def requestAny(self, **_kwargs):
            return 409, {"message": "ResourceExists"}, "{\"message\":\"ResourceExists\"}"

    executor = AnkeyRequestExecutor(ClientWithConflict())

    result = executor.execute(RequestSpec.post("/ankey/managed/user", payload={"x": 1}))

    assert result.ok is False
    assert result.error_reason == "resourceexists"
    assert result.error_code == ErrorCode.CONFLICT
    assert result.error_details is not None
    assert "body_snippet" in result.error_details


def test_executor_maps_invalid_json_api_error():
    class ClientWithInvalidJson:
        def requestAny(self, **_kwargs):
            raise ApiError("Invalid JSON response", status_code=200, code="INVALID_JSON")

    executor = AnkeyRequestExecutor(ClientWithInvalidJson())

    result = executor.execute(RequestSpec("GET", "/ankey/managed/user", expected_statuses=(200,)))

    assert result.ok is False
    assert result.error_code == ErrorCode.INVALID_JSON
