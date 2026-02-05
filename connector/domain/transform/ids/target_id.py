"""
Назначение:
    Генерация target_id/идентификаторов sink.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

D = TypeVar("D")


class TargetIdMode:
    """
    Назначение:
        Режим обработки target_id.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    NONE = "none"


@dataclass(frozen=True)
class TargetIdPolicy(Generic[D]):
    """
    Назначение:
        Политика формирования target_id для конкретного датасета.
    """

    field_name: str = "target_id"
    mode: str = TargetIdMode.REQUIRED
    allow_source_value: bool = True
    generator: Callable[[], str] | None = None
    exists: Callable[[D, str], bool] | None = None
    max_attempts: int = 3

__all__ = ["TargetIdMode", "TargetIdPolicy"]
