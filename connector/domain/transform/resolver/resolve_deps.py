"""
Назначение:
    Зависимости resolve-стадии.

    ResolverSettings — domain value-object для resolver/pending механики.
"""

from __future__ import annotations

from dataclasses import dataclass


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
