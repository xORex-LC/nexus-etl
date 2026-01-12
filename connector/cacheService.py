from __future__ import annotations

import logging
from typing import Any

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
from .cacheSourceJson import loadOrganizationsFromJson, loadUsersFromJson
from .loggingSetup import logEvent
from .timeUtils import getUtcNowIso

def _append_item(report, entity_type: str, key: str, status: str, error: str | None = None) -> None:
    report.items.append(
        {
            "entity_type": entity_type,
            "key": key,
            "status": status,
            "error": error,
        }
    )

def refreshCacheFromJson(
    conn,
    usersJsonPath: str | None,
    orgJsonPath: str | None,
    logger,
    report,
) -> dict[str, Any]:
    """
    Обновляет кэш из JSON файлов в одной транзакции.
    """
    if not usersJsonPath and not orgJsonPath:
        raise ValueError("At least one of usersJsonPath/orgJsonPath must be provided")

    ensureSchema(conn)

    inserted_users = updated_users = failed_users = 0
    inserted_orgs = updated_orgs = failed_orgs = 0
    runId = getattr(report.meta, "run_id", "unknown")

    try:
        conn.execute("BEGIN")

        if orgJsonPath:
            organizations = loadOrganizationsFromJson(orgJsonPath)
            for org in organizations:
                key = str(org.get("_ouid"))
                try:
                    status = upsertOrganization(conn, org)
                    if status == "inserted":
                        inserted_orgs += 1
                    else:
                        updated_orgs += 1
                    _append_item(report, "org", key, status)
                except Exception as exc:
                    failed_orgs += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert org {key}: {exc}")
                    _append_item(report, "org", key, "failed", str(exc))

        if usersJsonPath:
            users = loadUsersFromJson(usersJsonPath)
            for user in users:
                key = str(user.get("_id"))
                try:
                    status = upsertUser(conn, user)
                    if status == "inserted":
                        inserted_users += 1
                    else:
                        updated_users += 1
                    _append_item(report, "user", key, status)
                except Exception as exc:
                    failed_users += 1
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to upsert user {key}: {exc}")
                    _append_item(report, "user", key, "failed", str(exc))

        usersCount, orgCount = getCounts(conn)
        nowIso = getUtcNowIso()

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

    summary = {
        "users_inserted": inserted_users,
        "users_updated": updated_users,
        "users_failed": failed_users,
        "orgs_inserted": inserted_orgs,
        "orgs_updated": updated_orgs,
        "orgs_failed": failed_orgs,
        "users_count": usersCount,
        "org_count": orgCount,
    }
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
    }

    meta_users_count = _safe_int(getMetaValue(conn, "users_count"))
    meta_org_count = _safe_int(getMetaValue(conn, "org_count"))
    status["meta_users_count"] = meta_users_count
    status["meta_org_count"] = meta_org_count
    return status
