"""Совместимый вход в Ankey TargetSpec (legacy import path)."""

from __future__ import annotations

from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec

__all__ = ["build_ankey_spec"]
