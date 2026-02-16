"""Совместимый вход в Ankey provider (legacy import path)."""

from __future__ import annotations

from connector.infra.target.providers.ankey_rest.provider import (
    AnkeyTargetProvider,
    apply_retry_overrides,
)

__all__ = ["AnkeyTargetProvider", "apply_retry_overrides"]
