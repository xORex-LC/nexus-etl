from __future__ import annotations

from connector.domain.ports.execution import RequestSpec
from connector.infra.http.request_executor import AnkeyRequestExecutor


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
