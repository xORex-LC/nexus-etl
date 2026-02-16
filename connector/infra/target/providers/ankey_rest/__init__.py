"""Ankey REST provider (совместимый пакет-обёртка)."""

from __future__ import annotations

from connector.infra.target.providers.ankey_rest.driver import AnkeyHttpDriver
from connector.infra.target.providers.ankey_rest.provider import (
    AnkeyTargetProvider,
    apply_retry_overrides,
)
from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec

__all__ = [
    "AnkeyHttpDriver",
    "AnkeyTargetProvider",
    "apply_retry_overrides",
    "build_user_upsert_payload",
    "build_ankey_spec",
]
