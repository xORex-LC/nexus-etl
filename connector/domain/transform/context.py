"""
Назначение:
    Scoped execution context для pipeline-стадий.

    PipelineMetadata — иммутабельные метаданные запуска (run_id, dataset, catalog).
    StageExecutionContext — scoped контейнер capabilities для одной стадии
    (pay-for-what-you-use: стадия видит только те ports, которые ей разрешены).

Граница ответственности:
    - Owns: PipelineMetadata, StageExecutionContext, MissingCapabilityError.
    - Does NOT: собирать capabilities (это задача DI/factory layer).
    - Does NOT: содержать бизнес-логику — только scoped access к capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform_dsl.specs import SinkSpec

T = TypeVar("T")


@dataclass(frozen=True)
class PipelineMetadata:
    """
    Назначение:
        Иммутабельные метаданные запуска pipeline (общие для всех стадий).
    """

    run_id: str
    dataset_name: str
    catalog: ErrorCatalog
    sink_spec: SinkSpec | None = None


class MissingCapabilityError(Exception):
    """
    Назначение:
        Исключение при запросе capability, не зарегистрированной в context.

    Содержит port_type и список доступных capabilities для диагностики.
    """

    def __init__(
        self,
        port_type: type,
        available: list[type],
    ) -> None:
        self.port_type = port_type
        self.available = available
        available_names = [t.__name__ for t in available]
        super().__init__(
            f"Capability {port_type.__name__} is not available. "
            f"Registered: {available_names}"
        )


class StageExecutionContext:
    """
    Назначение:
        Scoped execution context для одной стадии.

    Содержит метаданные pipeline + только те capabilities,
    которые разрешены данной стадии (pay-for-what-you-use).

    Инварианты:
        - Создаётся один раз при сборке стадии, не модифицируется в runtime.
        - _capabilities не имеет публичных сеттеров.
    """

    def __init__(
        self,
        metadata: PipelineMetadata,
        capabilities: dict[type, object],
    ) -> None:
        self._metadata = metadata
        self._capabilities = dict(capabilities)  # defensive copy

    @property
    def metadata(self) -> PipelineMetadata:
        return self._metadata

    def require(self, port_type: type[T]) -> T:
        """
        Назначение:
            Получить обязательную capability или raise MissingCapabilityError.

        Используется engine-классами для capabilities, без которых стадия не работает.
        """
        instance = self._capabilities.get(port_type)
        if instance is None:
            raise MissingCapabilityError(
                port_type=port_type,
                available=list(self._capabilities.keys()),
            )
        return instance  # type: ignore[return-value]

    def get(self, port_type: type[T]) -> T | None:
        """Получить capability или None (мягкий доступ)."""
        return self._capabilities.get(port_type)  # type: ignore[return-value]

    def has(self, port_type: type) -> bool:
        """Проверить наличие capability без получения экземпляра."""
        return port_type in self._capabilities
