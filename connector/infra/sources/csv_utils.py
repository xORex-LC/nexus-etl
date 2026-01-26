from __future__ import annotations


class CsvFormatError(Exception):
    """
    Назначение:
        Ошибка критического формата CSV (количество колонок и т.п.).
    """


def parseNull(value: str | None) -> str | None:
    """
    Назначение:
        Преобразует пустые/NULL значения в None и тримит строки.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "" or trimmed.lower() == "null":
        return None
    return trimmed
