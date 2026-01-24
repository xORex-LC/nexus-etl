from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class MatchKeyError(ValueError):
    """
    Назначение:
        Ошибка построения match_key при строгом режиме.
    """


@dataclass(frozen=True)
class MatchKey:
    """
    Назначение:
        Value Object для match_key.
    """

    value: str


def _normalize_part(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def build_delimited_match_key(
    parts: Iterable[str | None],
    delimiter: str = "|",
    strict: bool = False,
) -> MatchKey:
    """
    Назначение:
        Построить match_key из списка частей с нормализацией пробелов.

    Контракт:
        - parts: набор строк/None
        - strict=True -> MatchKeyError при отсутствии части
        - Возвращает MatchKey с delimiter-разделителем
    """
    normalized = [_normalize_part(part) for part in parts]
    if strict and any(part == "" for part in normalized):
        raise MatchKeyError("match_key parts are incomplete")
    return MatchKey(value=delimiter.join(normalized))
