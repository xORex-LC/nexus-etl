"""
Назначение:
    Унифицированный runtime-контейнер зависимостей для transform-стадий.

    Deprecated: используйте StageExecutionContext (DEC-004).
    TransformProviderDeps сохранён для обратной совместимости на переходный период.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from connector.domain.ports.cache.roles import EnrichLookupPort
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort


@dataclass(frozen=True)
class TransformProviderDeps:
    """
    Назначение:
        Общие зависимости, которые могут использовать lookup/exists провайдеры.

    Deprecated:
        Используйте StageExecutionContext (DEC-004) для scoped capabilities.
        Будет удалён в DEC-004 Stage 5.
    """

    cache_gateway: EnrichLookupPort | None = None
    secret_store: SecretStoreProtocol | None = None
    dictionaries: DictionaryProviderPort | None = None

    def __post_init__(self) -> None:
        warnings.warn(
            "TransformProviderDeps is deprecated; "
            "use StageExecutionContext (DEC-004) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
