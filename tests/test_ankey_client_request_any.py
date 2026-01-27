from __future__ import annotations

import json

import httpx
import pytest

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError


def make_client(transport: httpx.BaseTransport, *, retries: int = 0) -> AnkeyApiClient:
    return AnkeyApiClient(
        baseUrl="https://ankey.local",
        username="user",
        password="pass",
        retries=retries,
        retryBackoffSeconds=0,
        transport=transport,
    )


def test_request_any_sends_json_payload():
    payload = {"name": "Jane", "active": True}

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/ankey/managed/user"
        body = json.loads(request.content.decode("utf-8"))
        assert body == payload
        return httpx.Response(200, json={"ok": True})

    client = make_client(httpx.MockTransport(responder))

    status, data, snippet = client.requestAny("POST", "/ankey/managed/user", json=payload)

    assert status == 200
    assert data == {"ok": True}
    assert snippet is not None
    assert snippet.startswith("{")


def test_request_any_returns_text_when_invalid_json():
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = make_client(httpx.MockTransport(responder))

    status, data, snippet = client.requestAny("GET", "/ankey/managed/user")

    assert status == 200
    assert data == "not-json"
    assert snippet == "not-json"


def test_request_any_retries_on_500_and_succeeds():
    calls = {"count": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, text="fail")
        return httpx.Response(200, json={"ok": True})

    client = make_client(httpx.MockTransport(responder), retries=1)

    status, data, _snippet = client.requestAny("GET", "/ankey/managed/user")

    assert status == 200
    assert data == {"ok": True}
    assert client.getRetryAttempts() == 1


def test_request_any_raises_api_error_on_network_after_retries():
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.TransportError("boom")

    client = make_client(httpx.MockTransport(responder), retries=0)

    with pytest.raises(ApiError) as exc:
        client.requestAny("GET", "/ankey/managed/user")

    assert exc.value.code == "NETWORK_ERROR"
