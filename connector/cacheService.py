from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from .ankeyApiClient import AnkeyApiClient, ApiError
from .cacheDb import ensureSchema
from .cacheRepo import (
    clearOrgs,
    clearUsers,
    getCounts,
    getMetaValue,
    setMetaValue,
    upsertOrganization,
    upsertUser,
)
from .cacheSourceApi import mapOrgFromApi, mapUserFromApi
from .cacheSourceJson import loadOrganizationsFromJson, loadUsersFromJson
from .loggingSetup import logEvent
from .timeUtils import getNowIso

def _append_item(report, entity_type: str, key: str, status: str, error: str | None = None) -> dict:
    item = {
        "entity_type": entity_type,
        "key": key,
        "status": status,
        "errors": [] if error is None else [{"code": "CACHE_ERROR", "field": None, "message": error}],
        "warnings": [],
    }
    report.items.append(item)
    return item


def _append_item_limited(report, entity_type: str, key: str, status: str, error: str | None, reportItemsLimit: int, includeSuccess: bool) -> None:
    # Always keep failed/skipped until limit; success only if includeSuccess
    if status not in ("failed", "skipped") and not includeSuccess:
        return
    if len(report.items) >= reportItemsLimit:
        try:
            report.meta.items_truncated = True
        except Exception:
            pass
        return
    _append_item(report, entity_type, key, status, error)

def refreshCacheFromJson(
    conn,
    usersJsonPath: str | None,
    orgJsonPath: str | None,
    logger,
    report,
    reportItemsLimit: int,
    reportItemsSuccess: bool,
) -> dict[str, Any]:
    """
    Обновляет кэш из JSON файлов в одной транзакции.
    """
    if not usersJsonPath and not orgJsonPath:
        raise ValueError("At least one of usersJsonPath/orgJsonPath must be provided")

    ensureSchema(conn)

    inserted_users = updated_users = failed_users = 0
    skipped_deleted_users = 0
    inserted_orgs = updated_orgs = failed_orgs = 0
    runId = getattr(report.meta, "run_id", "unknown")
    start_monotonic = time.monotonic()
    report.meta.page_size = None
    report.meta.max_pages = None
    report.meta.timeout_seconds = None
    report.meta.retries = None
    report.meta.include_deleted_users = False
    report.meta.skipped_deleted_users = 0
    logEvent(logger, logging.INFO, runId, "cache", "cache-refresh start")

    try:
        conn.execute("BEGIN")

        org_errors: list[tuple[str, Exception]] = []
        user_errors: list[tuple[str, Exception]] = []

        if orgJsonPath:
            organizations = loadOrganizationsFromJson(orgJsonPath, errors=org_errors)
            if org_errors:
                for key, exc in org_errors:
                    failed_orgs += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to parse org {key}: {exc}")
                    _append_item_limited(report, "org", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)
            for org in organizations:
                key = str(org.get("_ouid"))
                try:
                    status = upsertOrganization(conn, org)
                    if status == "inserted":
                        inserted_orgs += 1
                    else:
                        updated_orgs += 1
                    _append_item_limited(report, "org", key, status, None, reportItemsLimit, reportItemsSuccess)
                except Exception as exc:
                    failed_orgs += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert org {key}: {exc}")
                    _append_item_limited(report, "org", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)

        if usersJsonPath:
            users = loadUsersFromJson(usersJsonPath, errors=user_errors)
            if user_errors:
                for key, exc in user_errors:
                    failed_users += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to parse user {key}: {exc}")
                    _append_item_limited(report, "user", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)
            for user in users:
                key = str(user.get("_id"))
                try:
                    status = upsertUser(conn, user)
                    if status == "inserted":
                        inserted_users += 1
                    else:
                        updated_users += 1
                    _append_item_limited(report, "user", key, status, None, reportItemsLimit, reportItemsSuccess)
                except Exception as exc:
                    failed_users += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert user {key}: {exc}")
                    _append_item_limited(report, "user", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)

        usersCount, orgCount = getCounts(conn)
        nowIso = getNowIso()

        setMetaValue(conn, "users_count", str(usersCount))
        setMetaValue(conn, "org_count", str(orgCount))

        if usersJsonPath:
            setMetaValue(conn, "users_last_refresh_at", nowIso)
            setMetaValue(conn, "source_users_json", str(usersJsonPath))
        if orgJsonPath:
            setMetaValue(conn, "org_last_refresh_at", nowIso)
            setMetaValue(conn, "source_org_json", str(orgJsonPath))

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logEvent(logger, logging.ERROR, runId, "cache", f"Cache refresh failed: {exc}")
        raise

    report.summary.created = inserted_users + inserted_orgs
    report.summary.updated = updated_users + updated_orgs
    report.summary.failed = failed_users + failed_orgs
    report.summary.skipped = skipped_deleted_users
    report.summary.retries_total = client.getRetryAttempts()
    report.meta.skipped_deleted_users = skipped_deleted_users

    summary = {
        "users_inserted": inserted_users,
        "users_updated": updated_users,
        "users_failed": failed_users,
        "users_skipped_deleted": skipped_deleted_users,
        "orgs_inserted": inserted_orgs,
        "orgs_updated": updated_orgs,
        "orgs_failed": failed_orgs,
        "users_count": usersCount,
        "org_count": orgCount,
    }
    duration_ms = int((time.monotonic() - start_monotonic) * 1000)
    logEvent(
        logger,
        logging.INFO,
        runId,
        "cache",
        f"cache-refresh done mode=json users_inserted={inserted_users} orgs_inserted={inserted_orgs} duration_ms={duration_ms}",
    )
    return summary


def refreshCacheFromApi(
    conn,
    settings,
    pageSize: int,
    maxPages: int | None,
    timeoutSeconds: float,
    retries: int,
    retryBackoffSeconds: float,
    logger,
    report,
    transport=None,
    includeDeletedUsers: bool = False,
    reportItemsLimit: int = 200,
    reportItemsSuccess: bool = False,
) -> dict[str, Any]:
    """
    Обновляет кэш из REST API с пагинацией.
    """
    ensureSchema(conn)
    runId = getattr(report.meta, "run_id", "unknown")

    baseUrl = f"https://{settings.host}:{settings.port}"
    client = AnkeyApiClient(
        baseUrl=baseUrl,
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=timeoutSeconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=retries,
        retryBackoffSeconds=retryBackoffSeconds,
        transport=transport,
    )
    client.resetRetryAttempts()

    inserted_users = updated_users = failed_users = skipped_deleted_users = 0
    deleted_included_users = 0
    inserted_orgs = updated_orgs = failed_orgs = 0
    pages_users = pages_orgs = 0
    error_stats: dict[str, int] = {}
    include_deleted = True if includeDeletedUsers is True else False
    logEvent(
        logger,
        logging.INFO,
        runId,
        "cache",
        f"cache-refresh start mode=api page_size={pageSize} max_pages={maxPages} include_deleted_users={include_deleted}",
    )
    start_monotonic = time.monotonic()

    try:
        conn.execute("BEGIN")

        # Organizations
        try:
            for page, items in client.getPagedItems("/ankey/managed/organization", pageSize, maxPages):
                pages_orgs = max(pages_orgs, page)
                logEvent(logger, logging.DEBUG, runId, "api", f"GET org page={page} rows={pageSize}")
                logEvent(logger, logging.DEBUG, runId, "api", f"org page={page} items={len(items)}")
                for org in items:
                    key = str(org.get("_ouid"))
                    try:
                        mapped = mapOrgFromApi(org)
                        status = upsertOrganization(conn, mapped)
                        if status == "inserted":
                            inserted_orgs += 1
                        else:
                            updated_orgs += 1
                        _append_item_limited(report, "org", key, status, None, reportItemsLimit, reportItemsSuccess)
                    except sqlite3.IntegrityError as exc:
                        failed_orgs += 1
                        logEvent(logger, logging.DEBUG, runId, "cache", f"Org upsert integrity error key={key}: {exc}")
                        _append_item_limited(report, "org", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)
                    except Exception as exc:
                        failed_orgs += 1
                        logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert org {key}: {exc}")
                        _append_item(report, "org", key, "failed", str(exc))
        except ApiError as exc:
            conn.rollback()
            logEvent(
                logger,
                logging.ERROR,
                runId,
                "cache",
                f"Org fetch failed: {exc} body={exc.body_snippet}",
            )
            raise

        # Users
        try:
            for page, items in client.getPagedItems("/ankey/managed/user", pageSize, maxPages):
                pages_users = max(pages_users, page)
                logEvent(logger, logging.DEBUG, runId, "api", f"GET user page={page} rows={pageSize}")
                logEvent(logger, logging.DEBUG, runId, "api", f"user page={page} items={len(items)}")
                for user in items:
                    key = str(user.get("_id"))
                    try:
                        if not include_deleted:
                            status_raw = user.get("accountStatus")
                            deletion_date = user.get("deletionDate")
                            status_norm = str(status_raw).strip().lower() if status_raw is not None else ""
                            deletion_norm = str(deletion_date).strip().lower() if deletion_date is not None else None
                            if status_norm == "deleted" or deletion_norm not in (None, "", "null"):
                                skipped_deleted_users += 1
                                _append_item_limited(report, "user", key, "skipped", None, reportItemsLimit, reportItemsSuccess)
                                continue
                        else:
                            status_raw = user.get("accountStatus")
                            deletion_date = user.get("deletionDate")
                            status_norm = str(status_raw).strip().lower() if status_raw is not None else ""
                            deletion_norm = str(deletion_date).strip().lower() if deletion_date is not None else None
                            if status_norm == "deleted" or deletion_norm not in (None, "", "null"):
                                deleted_included_users += 1
                        mapped = mapUserFromApi(user)
                        status = upsertUser(conn, mapped)
                        if status == "inserted":
                            inserted_users += 1
                        else:
                            updated_users += 1
                        _append_item_limited(report, "user", key, status, None, reportItemsLimit, reportItemsSuccess)
                        logEvent(
                            logger,
                            logging.DEBUG,
                            runId,
                            "cache",
                            f"upsert user key={key} status={status} inserted={inserted_users} updated={updated_users} skipped_deleted={skipped_deleted_users}",
                        )
                    except sqlite3.IntegrityError as exc:
                        failed_users += 1
                        logEvent(logger, logging.DEBUG, runId, "cache", f"User upsert integrity error key={key}: {exc}")
                        _append_item_limited(report, "user", key, "failed", str(exc), reportItemsLimit, reportItemsSuccess)
                    except Exception as exc:
                        failed_users += 1
                        logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert user {key}: {exc}")
                        _append_item(report, "user", key, "failed", str(exc))
        except ApiError as exc:
            conn.rollback()
            logEvent(
                logger,
                logging.ERROR,
                runId,
                "cache",
                f"User fetch failed: {exc} body={exc.body_snippet}",
            )
            code = exc.code if hasattr(exc, "code") else "API_ERROR"
            error_stats[code] = error_stats.get(code, 0) + 1
            raise

        usersCount, orgCount = getCounts(conn)
        nowIso = getNowIso()

        setMetaValue(conn, "users_count", str(usersCount))
        setMetaValue(conn, "org_count", str(orgCount))
        setMetaValue(conn, "users_last_refresh_at", nowIso)
        setMetaValue(conn, "org_last_refresh_at", nowIso)
        setMetaValue(conn, "source_api_base", baseUrl)

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logEvent(logger, logging.ERROR, runId, "cache", f"Cache refresh from API failed: {exc}")
        raise

    report.meta.pages_users = pages_users or None
    report.meta.pages_orgs = pages_orgs or None
    report.meta.api_base_url = baseUrl
    report.meta.page_size = pageSize
    report.meta.max_pages = maxPages
    report.meta.timeout_seconds = timeoutSeconds
    report.meta.retries = retries
    report.meta.retries_used = client.getRetryAttempts()
    report.meta.retry_backoff_seconds = retryBackoffSeconds
    report.meta.include_deleted_users = include_deleted
    report.meta.skipped_deleted_users = deleted_included_users if include_deleted else skipped_deleted_users

    report.summary.created = inserted_users + inserted_orgs
    report.summary.updated = updated_users + updated_orgs
    report.summary.failed = failed_users + failed_orgs
    report.summary.error_stats = error_stats
    report.summary.skipped = skipped_deleted_users
    report.summary.retries_total = client.getRetryAttempts()
    duration_ms = int((time.monotonic() - start_monotonic) * 1000)
    logEvent(
        logger,
        logging.INFO,
        runId,
        "cache",
        f"org phase: pages={pages_orgs} inserted={inserted_orgs} updated={updated_orgs} failed={failed_orgs}",
    )
    logEvent(
        logger,
        logging.INFO,
        runId,
        "cache",
        f"user phase: pages={pages_users} inserted={inserted_users} updated={updated_users} failed={failed_users} skipped_deleted={skipped_deleted_users}",
    )

    summary = {
        "users_inserted": inserted_users,
        "users_updated": updated_users,
        "users_failed": failed_users,
        "users_skipped_deleted": skipped_deleted_users,
        "orgs_inserted": inserted_orgs,
        "orgs_updated": updated_orgs,
        "orgs_failed": failed_orgs,
        "users_count": usersCount,
        "org_count": orgCount,
        "pages_users": pages_users,
        "pages_orgs": pages_orgs,
    }
    logEvent(
        logger,
        logging.INFO,
        runId,
        "cache",
        f"cache-refresh done users_count={usersCount} org_count={orgCount} duration_ms={duration_ms}",
    )
    return summary

def clearCache(conn) -> dict[str, int]:
    """
    Очищает таблицы users/organizations и сбрасывает meta счётчики.
    """
    ensureSchema(conn)
    conn.execute("BEGIN")
    try:
        users_deleted = clearUsers(conn)
        orgs_deleted = clearOrgs(conn)

        setMetaValue(conn, "users_count", "0")
        setMetaValue(conn, "org_count", "0")
        setMetaValue(conn, "users_last_refresh_at", None)
        setMetaValue(conn, "org_last_refresh_at", None)
        setMetaValue(conn, "source_users_json", None)
        setMetaValue(conn, "source_org_json", None)
        setMetaValue(conn, "source_api_base", None)

        conn.commit()
        return {"users_deleted": users_deleted, "orgs_deleted": orgs_deleted}
    except Exception:
        conn.rollback()
        raise

def _safe_int(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0

def getCacheStatus(conn) -> dict[str, Any]:
    """
    Возвращает состояние кэша: counts, last refresh, schema_version.
    """
    ensureSchema(conn)
    usersCount, orgCount = getCounts(conn)
    status = {
        "schema_version": getMetaValue(conn, "schema_version"),
        "users_count": usersCount,
        "org_count": orgCount,
        "users_last_refresh_at": getMetaValue(conn, "users_last_refresh_at"),
        "org_last_refresh_at": getMetaValue(conn, "org_last_refresh_at"),
        "source_api_base": getMetaValue(conn, "source_api_base"),
    }

    meta_users_count = _safe_int(getMetaValue(conn, "users_count"))
    meta_org_count = _safe_int(getMetaValue(conn, "org_count"))
    status["meta_users_count"] = meta_users_count
    status["meta_org_count"] = meta_org_count
    return status
