from __future__ import annotations

import logging
from typing import Any, Callable

from connector.infra.logging.setup import logEvent
from connector.domain.planning.plan_models import Plan
from connector.datasets.registry import get_spec
from connector.datasets.spec import DatasetSpec
from connector.domain.ports.execution import ExecutionResult, RequestExecutorProtocol
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.domain.exceptions import MissingRequiredSecretError
from connector.domain.planning.identity_keys import format_identity_key
from connector.domain.ports.identity_repository import IdentityRepository
from connector.common.sanitize import maskSecretsInObject
from connector.domain.models import DiagnosticStage, RowRef, ValidationErrorItem

class ImportApplyService:
    """
    Оркестратор выполнения плана импорта.
    """

    def __init__(
        self,
        executor: RequestExecutorProtocol,
        secrets: SecretProviderProtocol | None = None,
        spec_resolver: Callable[..., DatasetSpec] = get_spec,
        identity_repo: IdentityRepository | None = None,
        identity_keys: dict[str, set[str]] | None = None,
        identity_id_fields: dict[str, str] | None = None,
    ):
        self.executor = executor
        self.secrets = secrets
        self.spec_resolver = spec_resolver
        self.identity_repo = identity_repo
        self.identity_keys = identity_keys or {}
        self.identity_id_fields = identity_id_fields or {}

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
        if not dataset_name:
            raise ValueError("Plan meta.dataset is required for apply")
        dataset_spec = self.spec_resolver(dataset_name, secrets=self.secrets)
        apply_adapter = dataset_spec.get_apply_adapter()

        report.set_meta(dataset=dataset_name, items_limit=report_items_limit)

        def should_store(status: str) -> bool:
            return status in ("FAILED", "SKIPPED")

        for raw in plan.items:
            # План однородный: dataset берём строго из meta.
            item = raw
            item_dataset = dataset_name
            action = item.op
            if max_actions is not None and actions_count >= max_actions:
                break

            actions_count += 1
            if not item.resource_id:
                failed += 1
                if should_store("FAILED"):
                    report.add_item(
                        status="FAILED",
                        row_ref=self._build_row_ref(item),
                        payload=None,
                        errors=[
                            ValidationErrorItem(
                                stage=DiagnosticStage.APPLY,
                                code="RESOURCE_ID_MISSING",
                                field="resource_id",
                                message="resource_id is required",
                            )
                        ],
                        warnings=[],
                        meta=maskSecretsInObject(self._build_meta(item, None, None, None)),
                    )
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
                        status = "OK"
                        if should_store(status):
                            report.add_item(
                                status=status,
                                row_ref=self._build_row_ref(current_item),
                                payload=maskSecretsInObject(self._build_payload(current_item)),
                                errors=[],
                                warnings=[],
                                meta=maskSecretsInObject(
                                    self._build_meta(current_item, exec_result.status_code, exec_result.response_json, exec_result.error_details)
                                ),
                            )
                        if action == "create":
                            created += 1
                        elif action == "update":
                            updated += 1
                        self._update_identity_index(
                            dataset=item_dataset,
                            desired_state=current_item.desired_state,
                            response_json=exec_result.response_json,
                            source_ref=current_item.source_ref,
                        )
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
                    error_stats[code] = error_stats.get(code, 0) + 1
                    if should_store("FAILED"):
                        report.add_item(
                            status="FAILED",
                            row_ref=self._build_row_ref(current_item),
                            payload=maskSecretsInObject(self._build_payload(current_item)),
                            errors=[
                                ValidationErrorItem(
                                    stage=DiagnosticStage.APPLY,
                                    code=code,
                                    field=None,
                                    message=exec_result.error_message or "request failed",
                                )
                            ],
                            warnings=[],
                            meta=maskSecretsInObject(
                                self._build_meta(current_item, exec_result.status_code, exec_result.response_json, exec_result.error_details)
                            ),
                        )
                    if code in ("UNAUTHORIZED", "FORBIDDEN"):
                        fatal_error = True
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exec_result.error_message}")
                    break
                except MissingRequiredSecretError as exc:
                    failed += 1
                    err_code = exc.code.value
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    if should_store("FAILED"):
                        report.add_item(
                            status="FAILED",
                            row_ref=self._build_row_ref(current_item),
                            payload=maskSecretsInObject(self._build_payload(current_item)),
                            errors=[
                                ValidationErrorItem(
                                    stage=DiagnosticStage.APPLY,
                                    code=err_code,
                                    field=exc.field,
                                    message=str(exc),
                                )
                            ],
                            warnings=[],
                            meta=maskSecretsInObject(self._build_meta(current_item, None, None, None)),
                        )
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                    break
                except Exception as exc:
                    failed += 1
                    err_code = "UNEXPECTED_ERROR"
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    if should_store("FAILED"):
                        report.add_item(
                            status="FAILED",
                            row_ref=self._build_row_ref(current_item),
                            payload=maskSecretsInObject(self._build_payload(current_item)),
                            errors=[
                                ValidationErrorItem(
                                    stage=DiagnosticStage.APPLY,
                                    code=err_code,
                                    field=None,
                                    message=str(exc),
                                )
                            ],
                            warnings=[],
                            meta=maskSecretsInObject(self._build_meta(current_item, None, None, None)),
                        )
                    logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                    break

            if stop_on_first_error and failed:
                break

        retries_total = 0
        if hasattr(self.executor, "client") and hasattr(self.executor.client, "getRetryAttempts"):
            retries_total = self.executor.client.getRetryAttempts() or 0
        report.add_op("create", ok=created)
        report.add_op("update", ok=updated)
        report.add_op("skip", count=skipped)
        report.add_op("apply_failed", failed=failed)
        report.set_context(
            "apply",
            {
                "retries_total": retries_total,
                "error_stats": error_stats,
            },
        )
        if fatal_error:
            return 2
        return 1 if failed > 0 else 0

    @staticmethod
    def _build_row_ref(item) -> RowRef:
        row_id = getattr(item, "row_id", None) or getattr(item, "id", None) or "row:unknown"
        return RowRef(
            line_no=0,
            row_id=str(row_id),
            identity_primary=None,
            identity_value=None,
        )

    @staticmethod
    def _build_payload(item) -> dict[str, Any]:
        return item.__dict__.copy()

    @staticmethod
    def _build_meta(item, status_code, api_response, error_details) -> dict[str, Any]:
        return {
            "op": getattr(item, "op", None),
            "resource_id": getattr(item, "resource_id", None),
            "changes": getattr(item, "changes", {}),
            "desired_state": getattr(item, "desired_state", {}),
            "status_code": status_code,
            "api_response": api_response,
            "error_details": error_details,
        }

    def _update_identity_index(
        self,
        *,
        dataset: str,
        desired_state: dict[str, Any],
        response_json: Any | None,
        source_ref: dict[str, Any] | None,
    ) -> None:
        if self.identity_repo is None:
            return
        key_names = self.identity_keys.get(dataset)
        if not key_names:
            return
        id_field = self.identity_id_fields.get(dataset, "_id")
        resolved_id = None
        if isinstance(response_json, dict):
            resolved_id = response_json.get(id_field)
        if resolved_id is None:
            resolved_id = desired_state.get(id_field)
        if resolved_id is None:
            return
        resolved_id_str = str(resolved_id).strip()
        if resolved_id_str == "":
            return
        for key_name in key_names:
            value = desired_state.get(key_name)
            if value is None and isinstance(source_ref, dict):
                value = source_ref.get(key_name)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str == "":
                continue
            identity_key = format_identity_key(key_name, value_str)
            self.identity_repo.upsert_identity(dataset, identity_key, resolved_id_str)
