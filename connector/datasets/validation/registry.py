from __future__ import annotations

from typing import TypeVar

from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.pipeline import DatasetValidator, RowValidator, ValidatorFactory
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.normalizer import Normalizer

N = TypeVar("N")
T = TypeVar("T")

class ValidatorRegistry:
    """
    Назначение/ответственность:
        Реестр валидаторов по датасетам (пока только employees).
    Взаимодействия:
        Собирает Row/Dataset валидаторы через ValidatorFactory для типизированных строк.
    Ограничения:
        Синхронный, не кеширует состояние.
    """

    def __init__(
        self,
        deps: ValidationDependencies,
        normalizer: Normalizer[N],
        mapper: SourceMapper[N, T],
        required_fields: tuple[tuple[str, str], ...] = (),
    ):
        self.deps = deps
        self.factory = ValidatorFactory(deps, normalizer, mapper, required_fields)

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
