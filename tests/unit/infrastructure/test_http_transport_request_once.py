from __future__ import annotations

import json

import httpx

from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)
from connector.infra.target.transports.http.normalizer import normalize_http_outcome
from connector.infra.target.transports.http.request_builder import HttpRequest
from connector.infra.target.transports.http.request_once import request_once


def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(
        HttpClientSettings(
            base_url="https://ankey.local",
            transport=transport,
        )
    )


def test_request_once_sends_json_payload() -> None:
    payload = {"name": "Jane", "active": True}

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/ankey/managed/user"
        body = json.loads(request.content.decode("utf-8"))
        assert body == payload
        return httpx.Response(200, json={"ok": True})

    client = _make_client(httpx.MockTransport(responder))
    try:
        outcome = request_once(
            client,
            HttpRequest(
                method="POST",
                path="/ankey/managed/user",
                query={},
                headers={},
                json=payload,
            ),
        )
    finally:
        client.close()

    assert outcome.error is None
    assert outcome.response is not None
    assert outcome.response.status_code == 200
    assert outcome.response.body == {"ok": True}
    assert outcome.response.body_snippet is not None


def test_request_once_returns_text_when_invalid_json() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = _make_client(httpx.MockTransport(responder))
    try:
        outcome = request_once(
            client,
            HttpRequest(
                method="GET",
                path="/ankey/managed/user",
                query={},
                headers={},
            ),
        )
    finally:
        client.close()

    normalized = normalize_http_outcome(outcome)
    assert normalized.status_code == 200
    assert normalized.body == "not-json"
    assert normalized.body_snippet == "not-json"
    assert normalized.error_code is None


def test_request_once_maps_network_error_to_transport_error() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.TransportError("boom")

    client = _make_client(httpx.MockTransport(responder))
    try:
        outcome = request_once(
            client,
            HttpRequest(
                method="GET",
                path="/ankey/managed/user",
                query={},
                headers={},
            ),
        )
    finally:
        client.close()

    normalized = normalize_http_outcome(outcome)
    assert normalized.status_code is None
    assert normalized.error_code == "NETWORK_ERROR"
    assert normalized.error_message is not None
