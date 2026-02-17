"""Контракты provider-слоя для сборки target runtime."""

from __future__ import annotations

from typing import Protocol

from connector.infra.target.core.runtime import TargetRuntime


class TargetProvider(Protocol):
    """Контракт провайдера target-инфраструктуры.

    Провайдер инкапсулирует wiring конкретной реализации транспорта и
    возвращает готовый ``TargetRuntime`` для delivery-слоя.
    """

    target_type: str

    def build_core_runtime(
        self,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime:
        """Собрать runtime конкретного target-провайдера.

        Args:
            transport: опциональный transport override (например, mock transport в тестах).
            include_reader: включать ли read-интерфейс в runtime.
        """
        ...
