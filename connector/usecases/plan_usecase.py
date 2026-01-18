from __future__ import annotations

import logging
from typing import Any

from connector.planning.plan_builder import PlanBuilder, PlanBuildResult
from connector.planning.registry import PlannerRegistry
from connector.validation.pipeline import logValidationFailure
from connector.validation.registry import ValidatorRegistry
from connector.validation.dataset_rules import ValidationRowResult

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
            dataset_validator.validate(employee, validation)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            desired = employee.__dict__.copy()
            match_key = validation.match_key

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
                desired_state=desired,
                line_no=validation.line_no,
                match_key=match_key,
            )
            if op_status == "conflict":
                builder.add_conflict(validation.line_no, match_key, warnings)
                continue
            if op_status == "skip":
                builder.add_skip(validation.line_no, match_key, warnings)
                continue
            if plan_item:
                builder.add_plan_item(plan_item)

        return builder.build()
