"""
Назначение:
    Зависимости resolve-стадии.

    PlanningDependencies deprecated — используйте StageExecutionContext (DEC-004).
    ResolverSettings — остаётся как domain value-object.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from connector.domain.ports.cache.roles import PlanningRuntimePort


@dataclass(frozen=True)
class ResolverSettings:
    """
    Назначение:
        Настройки поведения resolver/pending механики.
    """

    pending_ttl_seconds: int
    pending_max_attempts: int
    pending_sweep_interval_seconds: int
    pending_on_expire: str
    pending_allow_partial: bool
    pending_retention_days: int


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    Deprecated:
        Используйте StageExecutionContext (DEC-004) для scoped capabilities.
        Будет удалён в DEC-004 Stage 5.
    """

    cache_gateway: PlanningRuntimePort | None = None
    resolver_settings: ResolverSettings | None = None

    def __post_init__(self) -> None:
        warnings.warn(
            "PlanningDependencies is deprecated; "
            "use StageExecutionContext (DEC-004) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
