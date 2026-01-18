from __future__ import annotations

from typing import Iterable, Protocol

from connector.models import CsvRow

class RowSource(Protocol):
    """
    Назначение/ответственность:
        Источник нормализованных строк для валидатора/планировщика (абстракция над CSV/маппером).
    Взаимодействия:
        Потребляется пайплайнами validate/plan/apply.
    """

    def __iter__(self) -> Iterable[CsvRow]:
        """
        Контракт:
            Возвращает итерируемые CsvRow (с заполненными file_line_no/values).
        """
        ...
