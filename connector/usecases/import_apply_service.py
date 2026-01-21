from __future__ import annotations

import logging
from typing import Any, Callable

from connector.infra.logging.setup import logEvent
from connector.planModels import Plan
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.datasets.registry import get_spec
from connector.datasets.spec import DatasetSpec
from connector.domain.ports.execution import ExecutionResult, RequestExecutorProtocol
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.domain.exceptions import MissingRequiredSecretError
from connector.usecases.import_plan_service import ImportPlanService

class ImportApplyService:
    """
    Оркестратор выполнения плана импорта.
    """

    def __init__(
        self,
        executor: RequestExecutorProtocol,
        secrets: SecretProviderProtocol | None = None,
        spec_resolver: Callable[..., DatasetSpec] = get_spec,
    ):
        self.executor = executor
        self.secrets = secrets
        self.spec_resolver = spec_resolver

    def _append_item(self, report, item: dict[str, Any], status: str) -> None:
        report.items.append(
            {
                "row_id": item.get("row_id"),
                "op": item.get("op"),
                "entity_type": item.get("entity_type"),
                "resource_id": item.get("resource_id"),
                "status": status,
                "errors": item.get("errors", []),
                "changes": item.get("changes", {}),
                "desired_state": item.get("desired_state", {}),
                "api_status": item.get("api_status"),
                "api_response": item.get("api_response"),
                "error_details": item.get("error_details"),
            }
        )

    def applyPlan(
        self,
        plan: Plan,
        logger,
        report,
        run_id: str,
        stop_on_first_error: bool,
        max_actions: int | None,
        dry_run: bool,
        report_items_limit: int,
        resource_exists_retries: int,
    ) -> int:
        created = updated = failed = 0
        skipped = getattr(plan.summary, "skipped", 0) if plan and plan.summary else 0
        actions_count = 0
        error_stats: dict[str, int] = {}
        fatal_error = False

        dataset_name = getattr(plan.meta, "dataset", None)
        dataset_spec = None
        if dataset_name:
            try:
                dataset_spec = self.spec_resolver(dataset_name, secrets=self.secrets)
            except TypeError:
                dataset_spec = self.spec_resolver(dataset_name)
        apply_adapter = dataset_spec.get_apply_adapter() if dataset_spec else None

        def should_append(status: str) -> bool:
            if status not in ("failed", "skipped"):
                return False
            if len(report.items) >= report_items_limit:
                try:
                    report.meta.items_truncated = True
                except Exception:
                    pass
                return False
            return True

        for item in plan.items:
            action = item.op
            if action not in ("create", "update"):
                failed += 1
                if should_append("failed"):
                    self._append_item(report, item.__dict__, "failed")
                if stop_on_first_error:
                    break
                continue

            if max_actions is not None and actions_count >= max_actions:
                break

            actions_count += 1
            if not item.resource_id:
                failed += 1
                if should_append("failed"):
                    self._append_item(report, item.__dict__, "failed")
                if stop_on_first_error:
                    break
                continue

            retries_left = resource_exists_retries
            current_item = item
            while True:
                try:
                    if dry_run:
                        exec_result = ExecutionResult(
                            ok=True, status_code=200, response_json={"dry_run": True}, error_code=None, error_message=None
                        )
                    else:
                        if apply_adapter is None:
                            raise ValueError("Apply adapter is not configured")
                        request_spec = apply_adapter.to_request(current_item)
                        exec_result = self.executor.execute(request_spec)

                    if exec_result.ok:
                        result_item = current_item.__dict__.copy()
                        result_item["api_status"] = exec_result.status_code
                        result_item["api_response"] = exec_result.response_json
                        result_item["error_details"] = exec_result.error_details
                        status = "created" if action == "create" else "updated"
                        if should_append(status):
                            self._append_item(report, result_item, status)
                        if action == "create":
                            created += 1
                        else:
                            updated += 1
                        break

                    next_item = None
                    if not dry_run and apply_adapter:
                        next_item = apply_adapter.on_failed_request(current_item, exec_result, retries_left)
                    if next_item and retries_left > 0:
                        retries_left -= 1
                        current_item = next_item
                        continue

                    failed += 1
                    code = exec_result.error_code.name if exec_result.error_code else "API_ERROR"
                    err = {"code": code, "field": None, "message": exec_result.error_message or "request failed"}
                    error_stats[code] = error_stats.get(code, 0) + 1
                    result_item = current_item.__dict__.copy()
                    result_item["errors"] = list(result_item.get("errors", [])) + [err]
                    result_item["api_status"] = exec_result.status_code
                    result_item["api_response"] = exec_result.response_json
                    result_item["error_details"] = exec_result.error_details
                    if should_append("failed"):
                        self._append_item(report, result_item, "failed")
                    if code in ("UNAUTHORIZED", "FORBIDDEN"):
                        fatal_error = True
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {err['message']}")
                    break
                except MissingRequiredSecretError as exc:
                    failed += 1
                    err_code = exc.code.value
                    err = {"code": err_code, "field": exc.field, "message": str(exc)}
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    result_item = current_item.__dict__.copy()
                    result_item["errors"] = list(result_item.get("errors", [])) + [err]
                    if should_append("failed"):
                        self._append_item(report, result_item, "failed")
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                    break
                except Exception as exc:
                    failed += 1
                    err_code = "UNEXPECTED_ERROR"
                    err = {"code": err_code, "field": None, "message": str(exc)}
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    result_item = current_item.__dict__.copy()
                    result_item["errors"] = list(result_item.get("errors", [])) + [err]
                    if should_append("failed"):
                        self._append_item(report, result_item, "failed")
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                    break

            if stop_on_first_error and failed:
                break

        report.summary.created = created
        report.summary.updated = updated
        report.summary.skipped = skipped
        report.summary.failed = failed
        report.summary.error_stats = error_stats
        retries_total = 0
        if hasattr(self.executor, "client") and hasattr(self.executor.client, "getRetryAttempts"):
            retries_total = self.executor.client.getRetryAttempts() or 0
        report.summary.retries_total = retries_total
        if fatal_error:
            return 2
        return 1 if failed > 0 else 0

def readPlanFromCsv(
    conn,
    csv_path: str,
    csv_has_header: bool,
    include_deleted_users: bool,
    settings,
    dataset: str,
    logger,
    run_id: str,
    report,
    report_items_limit: int,
    include_skipped_in_report: bool,
    report_dir: str,
) -> Plan:
    service = ImportPlanService()
    service.run(
        conn=conn,
        csv_path=csv_path,
        csv_has_header=csv_has_header,
        include_deleted_users=include_deleted_users,
        settings=settings,
        dataset=dataset,
        logger=logger,
        run_id=run_id,
        report=report,
        report_items_limit=report_items_limit,
        include_skipped_in_report=include_skipped_in_report,
        report_dir=report_dir,
    )
    if service.last_plan:
        return service.last_plan
    plan_path = report.meta.plan_file
    if not plan_path:
        raise ValueError("plan file not created")
    return readPlanFile(plan_path)
