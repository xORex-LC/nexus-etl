from __future__ import annotations

from typing import Any, Callable

from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.pipeline import DatasetValidator, RowValidator, ValidatorFactory
from connector.domain.ports.sources import SourceMapper
from connector.domain.models import EmployeeInput

class ValidatorRegistry:
    """
    Назначение/ответственность:
        Реестр валидаторов по датасетам (пока только employees).
    Взаимодействия:
        Собирает Row/Dataset валидаторы через ValidatorFactory.
    Ограничения:
        Синхронный, не кеширует состояние.
    """

    def __init__(
        self,
        deps: ValidationDependencies,
        mapper: SourceMapper,
        legacy_adapter: Callable[[Any, dict[str, str]], EmployeeInput],
        required_fields: tuple[tuple[str, str], ...] = (),
    ):
        self.deps = deps
        self.factory = ValidatorFactory(deps, mapper, legacy_adapter, required_fields)

    def create_row_validator(self) -> RowValidator:
        """
        Возвращает RowValidator для конкретного датасета.
        """
        return self.factory.create_row_validator()

    def create_dataset_validator(self, state: DatasetValidationState) -> DatasetValidator:
        """
        Возвращает DatasetValidator для конкретного датасета.
        """
        return self.factory.create_dataset_validator(state)

    def create_state(self) -> DatasetValidationState:
        """
        Возвращает новое состояние глобальных проверок.
        """
        return self.factory.create_validation_context()
