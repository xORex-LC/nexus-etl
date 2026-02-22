"""
Назначение:
    Registry-based factory для создания pipeline-стадий.

    StageDescriptor — frozen metadata для регистрации типа стадии.
    StageFactory — generic registry: create(stage_type, spec, context) → StageContract.

Граница ответственности:
    - Owns: registry stage_type → StageDescriptor, fail-fast capability проверка, create().
    - Does NOT: выполнять I/O (build_options приходят извне).
    - Does NOT: содержать бизнес-логику стадий.
    - Does NOT: регистрировать дескрипторы (это задача delivery layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from connector.domain.transform.context import (
    MissingCapabilityError,
    StageExecutionContext,
)
from connector.domain.transform.stages.stages import AnyStageContract


@dataclass(frozen=True)
class StageDescriptor:
    """
    Назначение:
        Metadata для регистрации типа стадии в StageFactory.

    Поля:
        stage_type: уникальный идентификатор типа стадии (e.g. "map", "enrich").
        engine_factory: (spec, context, **kwargs) → Engine.
        stage_wrapper: (engine, context) → StageContract.
        required_capabilities: ports, которые стадия требует через context.require().
    """

    stage_type: str
    engine_factory: Callable[..., object]
    stage_wrapper: Callable[[object, StageExecutionContext], AnyStageContract]
    required_capabilities: frozenset[type] = field(default_factory=frozenset)


class StageFactory:
    """
    Назначение:
        Registry-based factory для создания pipeline-стадий.

    Инварианты:
        - create() не выполняет I/O.
        - Неизвестный stage_type → ValueError.
        - Дублированная регистрация → ValueError.
        - required_capabilities проверяются ДО вызова engine_factory (fail-fast).

    Open/Closed: новая стадия = new StageDescriptor + register(), factory не меняется.
    """

    def __init__(self) -> None:
        self._registry: dict[str, StageDescriptor] = {}

    def register(self, descriptor: StageDescriptor) -> None:
        """
        Назначение:
            Зарегистрировать тип стадии.

        Raises:
            ValueError: если stage_type уже зарегистрирован.
        """
        if descriptor.stage_type in self._registry:
            raise ValueError(
                f"Stage type already registered: {descriptor.stage_type}"
            )
        self._registry[descriptor.stage_type] = descriptor

    @property
    def registered_types(self) -> list[str]:
        """Список зарегистрированных stage_type (для introspection)."""
        return list(self._registry.keys())

    def create(
        self,
        stage_type: str,
        spec: Any,
        context: StageExecutionContext,
        **kwargs: Any,
    ) -> AnyStageContract:
        """
        Назначение:
            Создать стадию по типу.

        Алгоритм:
            1. Найти descriptor по stage_type (ValueError если не найден).
            2. Проверить required_capabilities ДО создания engine (fail-fast).
            3. Вызвать engine_factory(spec, context, **kwargs).
            4. Вызвать stage_wrapper(engine, context) → StageContract.

        Raises:
            ValueError: если stage_type не зарегистрирован.
            MissingCapabilityError: если required capability отсутствует в context.
        """
        descriptor = self._registry.get(stage_type)
        if descriptor is None:
            raise ValueError(
                f"Unknown stage type: {stage_type}. "
                f"Registered: {list(self._registry.keys())}"
            )

        # Fail-fast: check capabilities BEFORE creating engine
        for cap in descriptor.required_capabilities:
            if not context.has(cap):
                raise MissingCapabilityError(
                    port_type=cap,
                    available=list(
                        k for k in context._capabilities.keys()  # noqa: SLF001
                    ),
                )

        engine = descriptor.engine_factory(spec, context, **kwargs)
        return descriptor.stage_wrapper(engine, context)
