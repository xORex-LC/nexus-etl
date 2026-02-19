"""
Назначение:
    Compile-policy опции для transform DSL стадий.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dsl.build_options import BaseDslBuildOptions


@dataclass(frozen=True)
class MapDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции map-стадии.
    """

    require_targets_exist_in_sink_spec: bool = False


@dataclass(frozen=True)
class NormalizeDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции normalize-стадии.
    """

    validate_only_touched_fields: bool = False


@dataclass(frozen=True)
class EnrichDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции enrich-стадии.
    """

    require_match_key: bool = False


@dataclass(frozen=True)
class MatchDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции match-стадии.
    """

    require_primary_identity_rule: bool = False


@dataclass(frozen=True)
class ResolveDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции resolve-стадии.
    """

    allow_pending_links: bool = True
