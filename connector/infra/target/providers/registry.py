"""Реестр target-провайдеров по умолчанию."""

from __future__ import annotations

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.registry import TargetProviderRegistry
from connector.infra.target.providers.ankey_rest import AnkeyTargetProvider


def build_default_target_provider_registry(api_settings: ApiSettings) -> TargetProviderRegistry:
    """Собрать реестр providers по умолчанию для production wiring."""
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(api_settings), default=True)
    return registry


__all__ = ["build_default_target_provider_registry"]
