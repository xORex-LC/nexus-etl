from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.pipeline import DatasetValidator, RowValidator
from connector.domain.planning.protocols import PlanningPolicyProtocol
from connector.domain.planning.deps import PlanningDependencies
from connector.domain.ports.execution import RequestSpec, ExecutionResult
from connector.domain.transform.result import TransformResult

@dataclass
class ValidatorBundle:
    """
    Назначение:
        Набор валидаторов и фабрика состояния для конкретного датасета.
    """
    row_validator: RowValidator
    dataset_validator: DatasetValidator
    state: DatasetValidationState

class ApplyAdapter(Protocol):
    """
    Назначение:
        Преобразует плановую операцию в спецификацию запроса на исполнение.
    Взаимодействия:
        Используется на слое apply для получения RequestSpec из PlanItem.
    """

    def to_request(self, item) -> RequestSpec: ...

    def on_failed_request(self, item, result: ExecutionResult, retries_left: int):
        """
        Назначение:
            Опционально предложить повторную попытку с модификацией PlanItem.
        Контракт:
            - Вернуть новый PlanItem для ретрая или None, чтобы прекратить попытки.
        """
        ...

@dataclass(frozen=True)
class ReportAdapter:
    """
    Назначение:
        Набор констант/лейблов для отчётов по датасету.
    """
    identity_label: str
    conflict_code: str
    conflict_field: str

class DatasetSpec(Protocol):
    """
    Назначение:
        Контракт плагина датасета: валидаторы, проектор, планировщик, отчётные настройки.
    """

    def build_validation_deps(self, conn, settings) -> ValidationDependencies: ...
    def build_planning_deps(self, conn, settings) -> PlanningDependencies: ...
    def build_enrich_deps(self, conn, settings, secret_store=None): ...
    def build_validators(self, deps: ValidationDependencies, enrich_deps) -> ValidatorBundle: ...
    def build_record_source(
        self,
        csv_path: str,
        csv_has_header: bool,
        source_format: str | None = None,
    ) -> Iterable[TransformResult[None]]: ...
    def build_planning_policy(self, include_deleted: bool, deps: PlanningDependencies) -> PlanningPolicyProtocol: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapter: ...
