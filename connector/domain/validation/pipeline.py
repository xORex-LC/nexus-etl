from __future__ import annotations

import logging
from typing import Protocol, TypeVar

from ..models import DiagnosticStage, RowRef, ValidationErrorItem, ValidationRowResult
from .deps import DatasetValidationState, ValidationDependencies
from .validated_row import ValidationRow
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.result import TransformResult

N = TypeVar("N")
T = TypeVar("T")
D = TypeVar("D")


class DatasetRule(Protocol[T]):
    """
    Назначение:
        Контракт для глобальных правил валидации набора строк.
    """

    def apply(
        self,
        row: T,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None: ...

class RowValidator(Protocol[T]):
    """
    Назначение/ответственность:
        Контракт строковой валидации для типизированных сущностей датасета.
    """

    def map_only(self, collected: TransformResult[None]) -> TransformResult[T]: ...
    def validate_enriched(self, map_result: TransformResult[T]) -> TransformResult[ValidationRow[T]]: ...


class TypedRowValidator:
    """
    Назначение/ответственность:
        Выполняет валидацию одной строки на уровне полей.

    Взаимодействия:
        - Использует SourceMapper для построения типизированной сущности.
        - Не выполняет глобальные проверки (уникальности, наличие org).
    """

    def __init__(
        self,
        normalizer: Normalizer[N],
        mapper: SourceMapper[T],
        enricher: Enricher[N, D],
        required_fields: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.normalizer = normalizer
        self.mapper = mapper
        self.enricher = enricher
        self.required_fields = required_fields

    def validate_enriched(self, map_result: TransformResult[T]) -> TransformResult[ValidationRow[T]]:
        """
        Назначение:
            Построить ValidationRowResult на основе обогащенной строки.
        """
        if map_result.row is not None:
            self._apply_required_fields(map_result)
        if map_result.row is None and not map_result.errors:
            raise ValueError("SourceMapper returned empty row for validation")

        match_key_value = map_result.match_key.value if map_result.match_key else ""
        match_key_complete = map_result.match_key is not None

        row_ref = map_result.row_ref or RowRef(
            line_no=map_result.record.line_no,
            row_id=map_result.record.record_id,
            identity_primary="match_key",
            identity_value=match_key_value or None,
        )

        result = ValidationRowResult(
            line_no=map_result.record.line_no,
            match_key=match_key_value,
            match_key_complete=match_key_complete,
            usr_org_tab_num=getattr(map_result.row, "usr_org_tab_num", None),
            row_ref=row_ref,
            secret_candidates=map_result.secret_candidates,
            errors=map_result.errors,
            warnings=map_result.warnings,
        )
        return TransformResult(
            record=map_result.record,
            row=ValidationRow(row=map_result.row, validation=result),
            row_ref=row_ref,
            match_key=map_result.match_key,
            secret_candidates=map_result.secret_candidates,
            errors=result.errors,
            warnings=result.warnings,
        )

    def map_only(self, collected: TransformResult[None]) -> TransformResult[T]:
        """
        Назначение:
            Вернуть чистый TransformResult без legacy-структур.
        """
        mapped = self.mapper.map(collected.record)
        mapped.errors = [*collected.errors, *mapped.errors]
        mapped.warnings = [*collected.warnings, *mapped.warnings]
        if mapped.errors:
            return mapped
        normalized = self.normalizer.normalize(mapped)
        if normalized.errors:
            return normalized
        return self.enricher.enrich(normalized)

    def _apply_required_fields(self, map_result) -> None:
        for attr_name, field_name in self.required_fields:
            value = getattr(map_result.row, attr_name, None)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                secret_value = map_result.secret_candidates.get(attr_name)
                if secret_value is not None and str(secret_value).strip() != "":
                    continue
                map_result.errors.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.VALIDATE,
                        code="REQUIRED_FIELD_MISSING",
                        field=field_name,
                        message=f"{field_name} is required",
                    )
                )

class DatasetValidator:
    """
    Назначение/ответственность:
        Применяет глобальные правила к результатам строковой валидации, используя
        общее состояние (уникальности, наличие связанных сущностей).
    """

    def __init__(
        self,
        rules: tuple[DatasetRule, ...],
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None:
        self.rules = rules
        self.state = state
        self.deps = deps

    def validate(self, row: T, result: ValidationRowResult) -> None:
        """
        Контракт:
            - Модифицирует result.errors/result.warnings, обновляет state.
        """
        for rule in self.rules:
            rule.apply(row, result, self.state, self.deps)

class ValidatorFactory:
    """
    Назначение/ответственность:
        Собирает валидаторы и контекст валидации, подставляя зависимости.
    """

    def __init__(
        self,
        deps: ValidationDependencies,
        normalizer: Normalizer[N],
        mapper: SourceMapper[N, T],
        enricher: Enricher[T, D],
        dataset_rules: tuple[DatasetRule[T], ...] = (),
        required_fields: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.deps = deps
        self.normalizer = normalizer
        self.mapper = mapper
        self.enricher = enricher
        self.dataset_rules = dataset_rules
        self.required_fields = required_fields

    def create_validation_context(self) -> DatasetValidationState:
        """
        Возвращает:
            DatasetValidationState — состояние глобальных проверок.
        """
        return DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})

    def create_row_validator(self) -> RowValidator[T]:
        """
        Возвращает:
            RowValidator на базе SourceMapper.
        """
        return TypedRowValidator(self.normalizer, self.mapper, self.enricher, self.required_fields)

    def create_dataset_validator(self, state: DatasetValidationState) -> DatasetValidator:
        """
        Возвращает:
            DatasetValidator с набором глобальных правил.
        """
        return DatasetValidator(
            rules=self.dataset_rules,
            state=state,
            deps=self.deps,
        )

# Совместимость: логирование валидации
def logValidationFailure(
    logger,
    run_id: str,
    context: str,
    result: ValidationRowResult,
    report_item_index: int | None,
    errors: list[ValidationErrorItem] | None = None,
    warnings: list[ValidationErrorItem] | None = None,
) -> None:
    """
    Назначение:
        Логирует информацию о невалидной строке CSV.
    """
    eff_errors = errors if errors is not None else result.errors
    eff_warnings = warnings if warnings is not None else result.warnings

    codes: list[str] = []
    codes.extend(e.code for e in eff_errors)
    codes.extend(w.code for w in eff_warnings)
    code_str = ",".join(sorted(set(codes))) if codes else "none"
    index_str = (
        str(report_item_index)
        if report_item_index is not None
        else f"line:{result.line_no} (not stored: limit reached)"
    )
    logger.log(
        logging.WARNING,
        f"invalid row line={result.line_no} report_item_index={index_str} errors={code_str}",
        extra={"runId": run_id, "component": context},
    )
