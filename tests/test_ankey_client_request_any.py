from __future__ import annotations

import json

import httpx

from connector.infra.http.ankey_client import AnkeyApiClient


def test_request_any_accepts_json_payload():
    seen = {}

    def responder(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(responder)
    client = AnkeyApiClient(
        baseUrl="https://api.local",
        username="u",
        password="p",
        timeoutSeconds=1,
        retries=0,
        retryBackoffSeconds=0,
        transport=transport,
    )

    payload = {"name": "Jane", "role": "dev"}
    status_code, resp, _snippet = client.requestAny("POST", "/path", json=payload)

    assert status_code == 200
    assert resp == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["path"] == "/path"
    assert json.loads(seen["body"].decode("utf-8")) == payload
