"""
Назначение:
    Compile-policy опции DSL для стадий трансформации.

Контракт:
    - Это не бизнес-правила датасета.
    - Источник значений: defaults -> global policy -> dataset.stage policy.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, TypeVar


@dataclass(frozen=True)
class BaseDslBuildOptions:
    """
    Назначение:
        Общие compile-policy флаги для всех DSL стадий.
    """

    strict: bool = False
    fail_on_unknown_ops: bool = True
    fail_on_schema_warnings: bool = False
    emit_compile_report: bool = False


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


TBuildOptions = TypeVar("TBuildOptions", bound=BaseDslBuildOptions)


def build_options_from_mapping(cls: type[TBuildOptions], data: dict[str, Any] | None) -> TBuildOptions:
    """
    Назначение:
        Безопасно собрать dataclass-опции из словаря.
    Алгоритм:
        - Игнорирует неизвестные ключи.
        - Использует значения по умолчанию для пропущенных полей.
    """

    if not data:
        return cls()
    allowed = {item.name for item in fields(cls)}
    kwargs = {key: value for key, value in data.items() if key in allowed}
    return cls(**kwargs)

