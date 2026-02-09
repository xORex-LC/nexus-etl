"""
Назначение:
    Унифицированный runtime-контейнер зависимостей для transform-стадий.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.cache.gateway import CacheGatewayPort
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort


@dataclass(frozen=True)
class TransformProviderDeps:
    """
    Назначение:
        Общие зависимости, которые могут использовать lookup/exists провайдеры.
    """

    cache_gateway: CacheGatewayPort
    secret_store: SecretStoreProtocol | None = None
    dictionaries: DictionaryProviderPort | None = None
