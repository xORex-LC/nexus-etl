from __future__ import annotations

import logging
from typing import Any, Protocol, Callable

from ..models import CsvRow, EmployeeInput, RowRef, ValidationErrorItem, ValidationRowResult
from .deps import DatasetValidationState, ValidationDependencies
from .dataset_rules import MatchKeyUniqueRule, OrgExistsRule, UsrOrgTabUniqueRule
from connector.domain.ports.sources import SourceMapper
from connector.infra.sources.employees_csv_record_adapter import EmployeesCsvRecordAdapter, CollectResult
# TODO: TECHDEBT - domain validation depends on infra adapter; remove after validator works with SourceRecord directly.
# TODO: TECHDEBT - clean up legacy imports/structures in validation pipeline after refactor.

class DatasetRule(Protocol):
    """
    Назначение:
        Контракт для глобальных правил валидации набора строк.
    """

    def apply(
        self,
        employee: EmployeeInput,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None: ...

class RowValidator:
    """
    Назначение/ответственность:
        Выполняет валидацию одной строки CSV на уровне полей (парсинг/формат).

    Взаимодействия:
        - Использует SourceMapper и адаптер к legacy EmployeeInput.
        - Не выполняет глобальные проверки (уникальности, наличие org).
    """

    def __init__(
        self,
        mapper: SourceMapper,
        legacy_adapter: Callable[[Any, dict[str, str]], EmployeeInput],
        record_adapter: EmployeesCsvRecordAdapter,
    ) -> None:
        self.mapper = mapper
        self.legacy_adapter = legacy_adapter
        self.record_adapter = record_adapter

    def validate(self, csv_row: CsvRow) -> tuple[EmployeeInput, ValidationRowResult]:
        """
        Контракт:
            csv_row: нормализованная строка CSV.
            Возвращает EmployeeInput + ValidationRowResult с ошибками/варнингами полей.
        """
        map_result = self.map_only(csv_row)
        employee = self.legacy_adapter(map_result.row, map_result.secret_candidates)

        match_key_value = map_result.match_key.value if map_result.match_key else ""
        match_key_complete = map_result.match_key is not None

        row_ref = map_result.row_ref or RowRef(
            line_no=csv_row.file_line_no,
            row_id=f"line:{csv_row.file_line_no}",
            identity_primary="match_key",
            identity_value=match_key_value or None,
        )

        result = ValidationRowResult(
            line_no=csv_row.file_line_no,
            match_key=match_key_value,
            match_key_complete=match_key_complete,
            usr_org_tab_num=getattr(map_result.row, "usr_org_tab_num", None),
            row_ref=row_ref,
            secret_candidates=map_result.secret_candidates,
            errors=map_result.errors,
            warnings=map_result.warnings,
        )
        return employee, result

    def map_only(self, csv_row: CsvRow):
        """
        Назначение:
            Вернуть чистый MapResult без legacy-структур.
        """
        # TODO: remove CSV record adapter when validator stops working with CsvRow.
        collected: CollectResult = self.record_adapter.collect(csv_row)
        map_result = self.mapper.map(collected.record)
        map_result.errors = [*collected.errors, *map_result.errors]
        map_result.warnings = [*collected.warnings, *map_result.warnings]
        return map_result

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

    def validate(self, employee: EmployeeInput, result: ValidationRowResult) -> None:
        """
        Контракт:
            - Модифицирует result.errors/result.warnings, обновляет state.
        """
        for rule in self.rules:
            rule.apply(employee, result, self.state, self.deps)

class ValidatorFactory:
    """
    Назначение/ответственность:
        Собирает валидаторы и контекст валидации, подставляя зависимости.
    """

    def __init__(
        self,
        deps: ValidationDependencies,
        mapper: SourceMapper,
        legacy_adapter: Callable[[Any, dict[str, str]], EmployeeInput],
        record_adapter: EmployeesCsvRecordAdapter,
    ) -> None:
        self.deps = deps
        self.mapper = mapper
        self.legacy_adapter = legacy_adapter
        self.record_adapter = record_adapter

    def create_validation_context(self) -> DatasetValidationState:
        """
        Возвращает:
            DatasetValidationState — состояние глобальных проверок.
        """
        return DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})

    def create_row_validator(self) -> RowValidator:
        """
        Возвращает:
            RowValidator на базе SourceMapper.
        """
        return RowValidator(self.mapper, self.legacy_adapter, self.record_adapter)

    def create_dataset_validator(self, state: DatasetValidationState) -> DatasetValidator:
        """
        Возвращает:
            DatasetValidator с набором глобальных правил.
        """
        dataset_rules: tuple[DatasetRule, ...] = (
            MatchKeyUniqueRule(),
            UsrOrgTabUniqueRule(),
            OrgExistsRule(),
        )
        return DatasetValidator(
            rules=dataset_rules,
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
