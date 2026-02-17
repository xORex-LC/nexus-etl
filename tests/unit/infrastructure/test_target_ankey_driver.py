from __future__ import annotations

import httpx
import pytest

from connector.infra.target.providers.ankey_rest.driver import AnkeyHttpDriver
from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)
from connector.infra.target.transports.http.request_builder import HttpRequest
from connector.infra.target.driver import DriverError


def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(
        HttpClientSettings(
            base_url="https://ankey.local",
            transport=transport,
        )
    )


def test_execute_non_ok_extracts_provider_reason_and_retry_after() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"message": "Resource exists"},
            headers={"Retry-After": "2"},
        )

    client = _make_client(httpx.MockTransport(responder))
    try:
        driver = AnkeyHttpDriver(client)
        response = driver.execute(
            HttpRequest(
                method="PUT",
                path="/ankey/managed/user/u-1",
                query={},
                headers={},
                expected_statuses=(200, 201),
            ),
            payload={"name": "Alice"},
        )
    finally:
        client.close()

    assert response.ok is False
    assert response.answer_code == 409
    assert response.error_reason == "resourceexists"
    assert response.retry_after_s == 2.0


def test_iter_batches_stops_when_max_batches_reached() -> None:
    call_count = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[{"id": call_count}])

    client = _make_client(httpx.MockTransport(responder))
    try:
        driver = AnkeyHttpDriver(client)
        pages = list(
            driver.iter_batches(
                HttpRequest(
                    method="GET",
                    path="/ankey/managed/user",
                    query={"_queryFilter": "true"},
                    headers={},
                    expected_statuses=(200,),
                ),
                batch_size=1,
                max_batches=1,
            )
        )
    finally:
        client.close()

    assert pages == [(1, [{"id": 1}])]
    assert call_count == 1


def test_iter_batches_error_keeps_provider_reason() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"message": "resourceexists"})

    client = _make_client(httpx.MockTransport(responder))
    try:
        driver = AnkeyHttpDriver(client)
        with pytest.raises(DriverError) as exc_info:
            list(
                driver.iter_batches(
                    HttpRequest(
                        method="GET",
                        path="/ankey/managed/user",
                        query={"_queryFilter": "true"},
                        headers={},
                        expected_statuses=(200,),
                    ),
                    batch_size=100,
                    max_batches=1,
                )
            )
    finally:
        client.close()

    assert exc_info.value.answer_code == 409
    assert exc_info.value.error_reason == "resourceexists"
