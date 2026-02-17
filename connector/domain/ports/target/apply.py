"""
Назначение:
    Доменный порт преобразования плановых операций в target request intent.
"""

from __future__ import annotations

from typing import Protocol

from connector.domain.planning.plan_models import PlanItem
from connector.domain.ports.target.execution import RequestSpec


class ApplyAdapterProtocol(Protocol):
    """
    Контракт адаптера apply:
        Принимает `PlanItem` и возвращает `RequestSpec`, который может быть
        исполнен `RequestExecutorProtocol` без знания конкретного транспорта.
    """

    def to_request(self, item: PlanItem) -> RequestSpec:
        """
        Построить transport-agnostic intent для одного элемента плана.

        Ошибки:
            Реализация может выбрасывать доменные исключения конфигурации данных,
            например отсутствие обязательного секрета.
        """
        ...


__all__ = ["ApplyAdapterProtocol"]
