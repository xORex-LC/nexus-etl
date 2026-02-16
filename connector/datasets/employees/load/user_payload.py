from __future__ import annotations

from typing import Any

from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)

def buildUserUpsertPayload(source: dict[str, Any]) -> dict[str, Any]:
    """
    Legacy-обёртка для миграционного периода.

    Payload-логика перенесена в provider-слой:
    `connector.infra.target.providers.ankey_rest.payloads.build_user_upsert_payload`.
    """
    return build_user_upsert_payload(source)
