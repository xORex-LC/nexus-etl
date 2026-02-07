"""
Назначение:
    Текстовые утилиты для transform/load слоёв.
"""

from __future__ import annotations


def normalize_text(
    value: object | None,
    *,
    empty_to_none: bool = False,
) -> str | None:
    """
    Назначение:
        Унифицированная нормализация текстовых значений.

    Контракт:
        - Схлопывает повторяющиеся пробелы.
        - `None` возвращает как `None`.
        - При `empty_to_none=True` пустая строка возвращается как `None`.
    """
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if empty_to_none and normalized == "":
        return None
    return normalized


def normalize_for_compare(value: object | None) -> str:
    """
    Назначение:
        Привести значение к канонической строке для сравнения.

    Контракт:
        - `None` преобразуется в пустую строку.
        - Повторяющиеся пробелы схлопываются.
        - Сравнение выполняется в `casefold` регистре.
    """
    normalized = normalize_text(value, empty_to_none=False)
    return (normalized or "").casefold()
