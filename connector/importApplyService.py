from __future__ import annotations

import logging
from typing import Any

from .ankeyApiClient import ApiError, AnkeyApiClient
from .importPlanService import ImportPlanService
from .loggingSetup import logEvent
from .planModels import Plan
from .planReader import readPlanFile
from .interfaces import UserApiProtocol
from .userApi import UserApi
from .userPayloadBuilder import buildUserUpsertPayload


class ImportApplyService:
    """
    Оркестратор выполнения плана импорта.
    """

    def __init__(self, user_api: UserApiProtocol):
        self.user_api = user_api

    def _append_item(self, report, item: dict[str, Any], status: str) -> None:
        report.items.append(
            {
                "row_id": item.get("row_id"),
                "action": item.get("action"),
                "match_key": item.get("match_key"),
                "existing_id": item.get("existing_id"),
                "new_id": item.get("new_id"),
                "status": status,
                "errors": item.get("errors", []),
                "warnings": item.get("warnings", []),
                "diff": item.get("diff", {}),
                "api_status": item.get("api_status"),
                "api_response": item.get("api_response"),
                "api_body_snippet": item.get("api_body_snippet"),
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
        report_items_success: bool,
    ) -> int:
        created = updated = skipped = failed = 0
        actions_count = 0

        def should_append(status: str) -> bool:
            if status not in ("failed", "skipped") and not report_items_success:
                return False
            return len(report.items) < report_items_limit

        for item in plan.items:
            action = item.action
            if action in ("skip", "error"):
                if action == "skip":
                    skipped += 1
                    status = "skipped"
                else:
                    failed += 1
                    status = "failed"
                if should_append(status):
                    self._append_item(report, item.__dict__, status)
                if action == "error" and stop_on_first_error:
                    break
                continue

            if max_actions is not None and actions_count >= max_actions:
                break

            actions_count += 1
            resource_id = item.new_id if action == "create" else item.existing_id
            if not resource_id:
                failed += 1
                if should_append("failed"):
                    self._append_item(report, item.__dict__, "failed")
                if stop_on_first_error:
                    break
                continue

            try:
                if not dry_run:
                    desired = item.desired if isinstance(item.desired, dict) else {}
                    if not desired:
                        raise ValueError("Plan item missing desired data")
                    payload = buildUserUpsertPayload(desired)
                    status_code, resp = self.user_api.upsertUser(resource_id, payload)
                else:
                    status_code, resp = 200, {"dry_run": True}
                result_item = item.__dict__.copy()
                result_item["api_status"] = status_code
                result_item["api_response"] = resp
                status = "created" if action == "create" else "updated"
                if should_append(status):
                    self._append_item(report, result_item, status)
                if action == "create":
                    created += 1
                else:
                    updated += 1
            except ApiError as exc:
                failed += 1
                err = {"code": "API_ERROR", "field": None, "message": str(exc)}
                result_item = item.__dict__.copy()
                result_item["errors"] = list(result_item.get("errors", [])) + [err]
                result_item["api_status"] = exc.status_code
                result_item["api_body_snippet"] = exc.body_snippet
                if should_append("failed"):
                    self._append_item(report, result_item, "failed")
                logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                if stop_on_first_error:
                    break
            except Exception as exc:
                failed += 1
                err = {"code": "UNEXPECTED_ERROR", "field": None, "message": str(exc)}
                result_item = item.__dict__.copy()
                result_item["errors"] = list(result_item.get("errors", [])) + [err]
                if should_append("failed"):
                    self._append_item(report, result_item, "failed")
                logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                if stop_on_first_error:
                    break

        report.summary.created = created
        report.summary.updated = updated
        report.summary.skipped = skipped
        report.summary.failed = failed
        return 1 if failed > 0 else 0


def readPlanFromCsv(
    conn,
    csv_path: str,
    csv_has_header: bool,
    include_deleted_users: bool,
    on_missing_org: str,
    logger,
    run_id: str,
    report,
    report_items_limit: int,
    report_items_success: bool,
    report_dir: str,
) -> Plan:
    service = ImportPlanService()
    service.run(
        conn=conn,
        csv_path=csv_path,
        csv_has_header=csv_has_header,
        include_deleted_users=include_deleted_users,
        on_missing_org=on_missing_org,
        logger=logger,
        run_id=run_id,
        report=report,
        report_items_limit=report_items_limit,
        report_items_success=report_items_success,
        report_dir=report_dir,
    )
    plan_path = report.meta.plan_file
    if not plan_path:
        raise ValueError("plan file not created")
    return readPlanFile(plan_path)


def createUserApiClient(settings, transport=None) -> UserApi:
    baseUrl = f"https://{settings.host}:{settings.port}"
    client = AnkeyApiClient(
        baseUrl=baseUrl,
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=settings.timeout_seconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=settings.retries,
        retryBackoffSeconds=settings.retry_backoff_seconds,
        transport=transport,
    )
    return UserApi(client)
