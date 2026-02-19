"""
Назначение:
    Generic compile-policy опции DSL.

    Layer-специфичные build options:
    - Transform: connector.domain.transform_dsl.build_options
    - Cache: connector.domain.cache_dsl.build_options

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
