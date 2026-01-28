from __future__ import annotations

import logging

from connector.infra.logging.setup import logEvent
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.common.time import getNowIso
from connector.usecases.plan_usecase import PlanUseCase
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.datasets.registry import get_spec

class ImportPlanService:
    """
    Оркестратор построения плана импорта.
    """

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted: bool,
        dataset: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        include_skipped_in_report: bool,
        report_dir: str,
        vault_file: str | None = None,
        settings=None,
    ) -> int:
        generated_at = getNowIso()

        dataset_spec = get_spec(dataset)
        validation_deps = dataset_spec.build_validation_deps(conn, settings)
        secret_store = None
        if vault_file:
            from connector.infra.secrets.file_vault_provider import FileVaultSecretStore

            secret_store = FileVaultSecretStore(vault_file)
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
        planning_deps = dataset_spec.build_planning_deps(conn, settings)
        row_source = dataset_spec.build_record_source(
            csv_path=csv_path,
            csv_has_header=csv_has_header,
        )
        transform_bundle = dataset_spec.build_transformers(validation_deps, enrich_deps)
        transformer = transform_bundle.build_pipeline()
        validator_bundle = dataset_spec.build_validator(validation_deps)
        validator = validator_bundle.validator
        enrich_usecase = EnrichUseCase(
            report_items_limit=report_items_limit,
            include_enriched_items=False,
        )
        enriched = enrich_usecase.iter_enriched(
            row_source=row_source,
            transformer=transformer,
        )
        validate_usecase = ValidateUseCase(
            report_items_limit=report_items_limit,
            include_valid_items=False,
        )
        validated_rows = validate_usecase.iter_validated(
            enriched_source=enriched,
            validator=validator,
        )
        use_case = PlanUseCase(
            report_items_limit=report_items_limit,
            include_skipped_in_report=include_skipped_in_report,
        )
        plan_result = use_case.run(
            validated_row_source=validated_rows,
            dataset_spec=dataset_spec,
            dataset=dataset,
            include_deleted=include_deleted,
            logger=logger,
            run_id=run_id,
            planning_deps=planning_deps,
            report=report,
        )
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted": include_deleted,
            "dataset": dataset,
        }
        plan_path = write_plan_file(
            plan_items=plan_result.items,
            summary=plan_result.summary_as_dict(),
            meta=plan_meta,
            report_dir=report_dir,
            run_id=run_id,
            generated_at=generated_at,
        )
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")

        report.set_meta(dataset=dataset, items_limit=report_items_limit)
        report.set_context(
            "plan",
            {
                "plan_file": plan_path,
                "include_deleted": include_deleted,
                "rows_total": plan_result.summary.rows_total,
                "valid_rows": plan_result.summary.valid_rows,
                "failed_rows": plan_result.summary.failed_rows,
                "planned_create": plan_result.summary.planned_create,
                "planned_update": plan_result.summary.planned_update,
                "skipped": plan_result.summary.skipped,
            },
        )
        report.add_op("create", count=plan_result.summary.planned_create)
        report.add_op("update", count=plan_result.summary.planned_update)
        report.add_op("skip", count=plan_result.summary.skipped)

        return 1 if plan_result.summary.failed_rows > 0 else 0
