from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from connector.datasets.spec import DatasetSpec
from connector.domain.models import Identity
from connector.domain.planning.plan_builder import PlanBuilder, PlanBuildResult
from connector.domain.validation.pipeline import logValidationFailure
from connector.domain.validation.dataset_rules import ValidationRowResult
from connector.domain.planning.protocols import PlanningKind, PlanningResult

@dataclass
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
        report_items_limit: int,
        include_skipped_in_report: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_skipped_in_report = include_skipped_in_report

    def run(
        self,
        row_source,
        dataset_spec: DatasetSpec,
        include_deleted_users: bool,
        logger: logging.Logger,
        run_id: str,
        validation_deps,
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
        report_adapter = dataset_spec.get_report_adapter()
        builder = PlanBuilder(
            include_skipped_in_report=self.include_skipped_in_report,
            report_items_limit=self.report_items_limit,
            identity_label=report_adapter.identity_label,
            conflict_code=report_adapter.conflict_code,
            conflict_field=report_adapter.conflict_field,
        )

        validators = dataset_spec.build_validators(validation_deps)
        row_validator = validators.row_validator
        dataset_validator = validators.dataset_validator
        entity_planner = dataset_spec.build_planner(include_deleted_users=include_deleted_users)
        projector = dataset_spec.get_projector()

        for csv_row in row_source:
            builder.inc_rows_total()
            employee, validation = row_validator.validate(csv_row)
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

            desired_state = projector.to_desired_state(employee)
            identity: Identity = projector.to_identity(employee, validation)
            # source_ref строится позже в планировщике/плане

            builder.inc_valid_rows()
            plan_result: PlanningResult = entity_planner.plan_row(
                desired_state=desired_state,
                line_no=validation.line_no,
                identity=identity,
            )
            if plan_result.kind == PlanningKind.CONFLICT:
                builder.add_conflict(validation.line_no, identity.primary_value, warnings)
                continue
            if plan_result.kind == PlanningKind.SKIP:
                builder.add_skip(validation.line_no, identity.primary_value, warnings)
                continue
            if plan_result.item:
                builder.add_plan_item(plan_result.item)

        return builder.build()
