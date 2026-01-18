from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any
from dataclasses import dataclass

from connector.models import EmployeeInput
from connector.planning.plan_builder import PlanBuilder, PlanBuildResult
from connector.planning.registry import PlannerRegistry
from connector.validation.pipeline import logValidationFailure
from connector.validation.registry import ValidatorRegistry
from connector.validation.dataset_rules import ValidationRowResult

@dataclass
class ValidatedRow:
    """
    Назначение/ответственность:
        Унифицированное представление валидированной строки для планировщика.

    Поля:
        desired_state: dict[str, Any]
            Готовое состояние для API/планировщика (очищенное от служебных полей).
        identity: dict[str, Any]
            Ключ(и) для сопоставления (набор, а не фиксированное поле).
        line_no: int
            Номер строки в исходном CSV (для трассировки).
        row_id: str
            Удобный идентификатор строки (line:<n>).
    """
    desired_state: dict[str, Any]
    identity: dict[str, Any]
    line_no: int
    row_id: str

class PlanUseCase:
    """
    Назначение/ответственность:
        Use-case планирования импорта: читает строки, валидирует, планирует операции и
        собирает итог через PlanBuilder.

    Взаимодействия:
        - Использует ValidatorRegistry для получения валидаторов по dataset.
        - Использует PlannerRegistry для получения EntityPlanner по dataset.
        - Не знает об артефактах/файлах/last_plan.

    Ограничения:
        Синхронное выполнение; источники строк и зависимости передаются извне.
    """

    def __init__(
        self,
        validator_registry: ValidatorRegistry,
        planner_registry: PlannerRegistry,
        report_items_limit: int,
        include_skipped_in_report: bool,
    ) -> None:
        self.validator_registry = validator_registry
        self.planner_registry = planner_registry
        self.report_items_limit = report_items_limit
        self.include_skipped_in_report = include_skipped_in_report

    def run(
        self,
        row_source,
        dataset: str,
        include_deleted_users: bool,
        logger: logging.Logger,
        run_id: str,
    ) -> PlanBuildResult:
        """
        Контракт (вход/выход):
            Вход: row_source (Iterable[CsvRow]), dataset: str, include_deleted_users: bool, logger, run_id.
            Выход: PlanBuildResult (items, summary, report_items, items_truncated).
        Ошибки/исключения:
            Пробрасывает CsvFormatError/OSError и исключения зависимостей.
        Алгоритм:
            - Инициализирует валидаторы и планировщик по dataset.
            - Проходит строки: валидирует, планирует, накапливает builder.
            - Возвращает результат builder.build().
        """
        builder = PlanBuilder(
            include_skipped_in_report=self.include_skipped_in_report,
            report_items_limit=self.report_items_limit,
        )

        row_validator = self.validator_registry.create_row_validator(dataset)
        state = self.validator_registry.create_state()
        dataset_validator = self.validator_registry.create_dataset_validator(dataset, state)
        entity_planner = self.planner_registry.get(dataset=dataset, include_deleted_users=include_deleted_users)

        for csv_row in row_source:
            builder.inc_rows_total()
            employee, validation = row_validator.validate(csv_row)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            validated_row = self._project_validated_row(employee, validation)

            if errors:
                builder.add_invalid(validation, errors, warnings)
                logValidationFailure(
                    logger,
                    run_id,
                    "import-plan",
                    validation,
                    None,
                    errors=errors,
                    warnings=warnings,
                )
                continue

            # Глобальные правила применяются только к строкам без ошибок поля
            dataset_validator.validate(employee, validation)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            if errors:
                builder.add_invalid(validation, errors, warnings)
                logValidationFailure(
                    logger,
                    run_id,
                    "import-plan",
                    validation,
                    None,
                    errors=errors,
                    warnings=warnings,
                )
                continue

            builder.inc_valid_rows()
            op_status, plan_item, _match_result = entity_planner.plan_row(
                desired_state=validated_row.desired_state,
                line_no=validated_row.line_no,
                match_key=str(validated_row.identity.get("match_key", "")),
            )
            if op_status == "conflict":
                builder.add_conflict(validation.line_no, str(validated_row.identity.get("match_key", "")), warnings)
                continue
            if op_status == "skip":
                builder.add_skip(validation.line_no, str(validated_row.identity.get("match_key", "")), warnings)
                continue
            if plan_item:
                builder.add_plan_item(plan_item)

        return builder.build()

    def _project_validated_row(self, employee: EmployeeInput, validation: ValidationRowResult) -> ValidatedRow:
        """
        Назначение:
            Сформировать стандартизованное представление валидированной строки для планировщика.

        Контракт (вход/выход):
            Вход: EmployeeInput + ValidationRowResult.
            Выход: ValidatedRow с очищенным desired_state и identity (match_key и вспомогательные ключи).
        Ограничения:
            Работает с одним сотрудником; при добавлении новых сущностей потребуется аналогичная проекция.
        """
        desired_state = asdict(employee)
        identity = {
            "match_key": validation.match_key,
            "usr_org_tab_num": validation.usr_org_tab_num,
        }
        return ValidatedRow(
            desired_state=desired_state,
            identity=identity,
            line_no=validation.line_no,
            row_id=f"line:{validation.line_no}",
        )
