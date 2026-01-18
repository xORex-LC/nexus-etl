from __future__ import annotations

from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.pipeline import DatasetValidator, RowValidator, ValidatorFactory

class ValidatorRegistry:
    """
    Назначение/ответственность:
        Реестр валидаторов по датасетам (пока только employees).
    Взаимодействия:
        Собирает Row/Dataset валидаторы через ValidatorFactory.
    Ограничения:
        Синхронный, не кеширует состояние.
    """

    def __init__(self, deps: ValidationDependencies):
        self.deps = deps
        self.factory = ValidatorFactory(deps)

    def create_row_validator(self, dataset: str) -> RowValidator:
        """
        Возвращает RowValidator для заданного датасета.
        """
        if dataset != "employees":
            raise ValueError(f"Unsupported dataset: {dataset}")
        return self.factory.create_row_validator()

    def create_dataset_validator(self, dataset: str, state: DatasetValidationState) -> DatasetValidator:
        """
        Возвращает DatasetValidator для заданного датасета.
        """
        if dataset != "employees":
            raise ValueError(f"Unsupported dataset: {dataset}")
        return self.factory.create_dataset_validator(state)

    def create_state(self) -> DatasetValidationState:
        """
        Возвращает новое состояние глобальных проверок.
        """
        return self.factory.create_validation_context()
