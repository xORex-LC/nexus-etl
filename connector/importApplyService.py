from __future__ import annotations

import logging
import uuid
from typing import Any

from .ankeyApiClient import ApiError, AnkeyApiClient
from .importPlanService import ImportPlanService
from .loggingSetup import logEvent
from .planModels import Plan
from .planReader import readPlanFile
from .protocols_api import UserApiProtocol
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
                "resource_id": item.get("resource_id"),
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
        resource_exists_retries: int,
    ) -> int:
        created = updated = skipped = failed = 0
        actions_count = 0
        error_stats: dict[str, int] = {}
        fatal_error = False

        def should_append(status: str) -> bool:
            if status not in ("failed", "skipped") and not report_items_success:
                return False
            if len(report.items) >= report_items_limit:
                try:
                    report.meta.items_truncated = True
                except Exception:
                    pass
                return False
            return True

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
                    retries_left = resource_exists_retries
                    while True:
                        try:
                            status_code, resp = self.user_api.upsertUser(resource_id, payload)
                            break
                        except ApiError as exc:
                            if (
                                action == "create"
                                and exc.status_code == 403
                                and exc.body_snippet
                                and "resourceexists" in exc.body_snippet.lower()
                                and retries_left > 0
                            ):
                                retries_left -= 1
                                resource_id = str(uuid.uuid4())
                                continue
                            raise
                else:
                    status_code, resp = 200, {"dry_run": True}
                result_item = item.__dict__.copy()
                result_item["resource_id"] = resource_id
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
                # Фатальные ошибки авторизации — прекращаем выполнение сразу
                if exc.status_code in (401, 403):
                    fatal_error = True
                failed += 1
                err_code = exc.code or "API_ERROR"
                err = {"code": err_code, "field": None, "message": str(exc)}
                error_stats[err_code] = error_stats.get(err_code, 0) + 1
                result_item = item.__dict__.copy()
                result_item["resource_id"] = resource_id
                result_item["errors"] = list(result_item.get("errors", [])) + [err]
                result_item["api_status"] = exc.status_code
                result_item["api_body_snippet"] = exc.body_snippet
                if should_append("failed"):
                    self._append_item(report, result_item, "failed")
                logEvent(logger, logging.ERROR, run_id, "import-apply", f"Apply failed: {exc}")
                if stop_on_first_error or fatal_error:
                    break
            except Exception as exc:
                failed += 1
                err = {"code": "UNEXPECTED_ERROR", "field": None, "message": str(exc)}
                error_stats[err["code"]] = error_stats.get(err["code"], 0) + 1
                result_item = item.__dict__.copy()
                result_item["resource_id"] = resource_id
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
        report.summary.error_stats = error_stats
        retries_total = 0
        if hasattr(self.user_api, "client") and hasattr(self.user_api.client, "getRetryAttempts"):
            retries_total = self.user_api.client.getRetryAttempts() or 0
        report.summary.retries_total = retries_total
        if fatal_error:
            return 2
        return 1 if failed > 0 else 0


def readPlanFromCsv(
    conn,
    csv_path: str,
    csv_has_header: bool,
    include_deleted_users: bool,
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
        logger=logger,
        run_id=run_id,
        report=report,
        report_items_limit=report_items_limit,
        report_items_success=report_items_success,
        report_dir=report_dir,
    )
    if service.last_plan:
        return service.last_plan
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
    client.resetRetryAttempts()
    return UserApi(client)
