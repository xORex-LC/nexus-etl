from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from connector.datasets.spec import DatasetSpec
from connector.domain.planning.plan_builder import PlanBuilder, PlanBuildResult
from connector.domain.planning.generic_planner import GenericPlanner
from connector.domain.validation.validator import logValidationFailure

@dataclass
class PlanUseCase:
    """
    Назначение/ответственность:
        Use-case планирования импорта: читает строки, валидирует, планирует операции и
        собирает итог через PlanBuilder.

    Взаимодействия:
        - Использует DatasetSpec для получения политик и адаптеров планирования.
        - Не знает об артефактах/файлах и не хранит планы в памяти.

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
        validated_row_source,
        dataset_spec: DatasetSpec,
        dataset: str,
        include_deleted: bool,
        logger: logging.Logger,
        run_id: str,
        planning_deps,
    ) -> PlanBuildResult:
        """
        Контракт (вход/выход):
            Вход: validated_row_source (Iterable[TransformResult[ValidationRow]]), dataset_spec, include_deleted: bool,
                  logger, run_id, planning_deps.
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

        planning_policy = dataset_spec.build_planning_policy(
            include_deleted=include_deleted, deps=planning_deps
        )
        planner = GenericPlanner(policy=planning_policy, builder=builder)

        for validated in validated_row_source:
            builder.inc_rows_total()
            validation_row = validated.row
            validation = validation_row.validation
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
            planner.plan_validated_row(validation_row.row, validation, warnings)

        return builder.build()
