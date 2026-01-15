from __future__ import annotations

from typing import Any

from .ankeyApiClient import AnkeyApiClient
from .interfaces import UserApiProtocol


class UserApi(UserApiProtocol):
    """
    Gateway для user endpoint'ов.
    """

    def __init__(self, client: AnkeyApiClient):
        self.client = client

    def upsertUser(self, resourceId: str, payload: dict[str, Any]) -> tuple[int, Any]:
        path = f"/ankey/managed/user/{resourceId}"
        params = {"_prettyPrint": "true", "decrypt": "false"}
        return self.client.requestJson("PUT", path, params=params, jsonBody=payload)
