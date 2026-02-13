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


@dataclass(frozen=True)
class CacheDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции cache DSL компиляции.
    """

    require_sync_dataset_match: bool = True
    fail_on_unknown_dependencies: bool = True
    fail_on_unknown_pk_fields: bool = True
    fail_on_unknown_index_fields: bool = True
    fail_on_duplicate_projection_targets: bool = True
    fail_on_unknown_projection_targets: bool = True
    forbid_is_deleted_and_soft_delete_together: bool = True


TBuildOptions = TypeVar("TBuildOptions", bound=BaseDslBuildOptions)


def build_options_from_mapping(
    cls: type[TBuildOptions], data: dict[str, Any] | None, *, strict: bool = False
) -> TBuildOptions:
    """
    Назначение:
        Безопасно собрать dataclass-опции из словаря.
    Алгоритм:
        - По умолчанию игнорирует неизвестные ключи.
        - Если strict=True, бросает DslLoadError при наличии unknown keys.
        - Использует значения по умолчанию для пропущенных полей.
    """
    from connector.domain.dsl.issues import DslLoadError

    if not data:
        return cls()
    allowed = {item.name for item in fields(cls)}
    if strict:
        unknown = set(data.keys()) - allowed
        if unknown:
            raise DslLoadError(
                code="BUILD_OPTIONS_UNKNOWN_KEYS",
                message=f"Unknown build_options keys: {sorted(unknown)}",
                details={"unknown": sorted(unknown), "allowed": sorted(allowed)},
            )
    kwargs = {key: value for key, value in data.items() if key in allowed}
    options = cls(**kwargs)
    if getattr(options, "strict", False) and hasattr(options, "fail_on_unknown_ops"):
        if not getattr(options, "fail_on_unknown_ops"):
            # strict-mode cannot silently allow unknown operations.
            normalized_kwargs = {item.name: getattr(options, item.name) for item in fields(cls)}
            normalized_kwargs["fail_on_unknown_ops"] = True
            options = cls(**normalized_kwargs)
    return options
