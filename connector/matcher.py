from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cacheRepo import findUsersByMatchKey


def _is_deleted(user_row: dict[str, Any]) -> bool:
    status_raw = user_row.get("account_status")
    deletion_date = user_row.get("deletion_date")
    status_norm = str(status_raw).strip().lower() if status_raw is not None else ""
    deletion_norm = str(deletion_date).strip().lower() if deletion_date is not None else ""
    if status_norm == "deleted":
        return True
    if deletion_norm not in ("", "null"):
        return True
    return False

@dataclass
class MatchResult:
    status: str  # "not_found" | "matched" | "conflict"
    candidate: dict[str, Any] | None
    candidates: list[dict[str, Any]]


def matchEmployeeByMatchKey(conn, match_key: str, include_deleted_users: bool) -> MatchResult:
    candidates = findUsersByMatchKey(conn, match_key)
    if not include_deleted_users:
        candidates = [c for c in candidates if not _is_deleted(c)]

    if len(candidates) == 0:
        return MatchResult(status="not_found", candidate=None, candidates=[])
    if len(candidates) > 1:
        return MatchResult(status="conflict", candidate=None, candidates=candidates)
    return MatchResult(status="matched", candidate=candidates[0], candidates=candidates)
