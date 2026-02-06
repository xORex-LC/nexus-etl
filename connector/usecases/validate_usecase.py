from __future__ import annotations

import logging

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.result_processor import TransformResultProcessor


class ValidateUseCase:
    """
    Назначение/ответственность:
        Совместимый alias use-case для dry-run качества после enrich.

    Примечание:
        Отдельная validate-стадия удалена из ETL-конвейера.
        Этот use-case больше не запускает Validator и работает поверх
        потока результатов map/normalize/enrich.
    """

    def __init__(
        self,
        report_items_limit: int,
        include_valid_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_valid_items = include_valid_items

    def run(
        self,
        enriched_source,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
    ) -> CommandResult:
        _ = (logger, run_id)
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        processor = TransformResultProcessor(
            report=report,
            include_items=self.include_valid_items,
            context_key="validate",
            ok_label="valid_rows",
            failed_label="failed_rows",
        )

        for enriched in enriched_source:
            processor.process(enriched)

        return processor.finalize()
