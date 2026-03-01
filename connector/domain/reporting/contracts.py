"""
Назначение:
    Типизированные контракты report schema v2 для top-level keys и статуса item.

Граница ответственности:
    - Содержит только перечисления и вспомогательные normalizer-функции.
    - Не хранит состояние и не выполняет запись в report.
"""

from __future__ import annotations

from enum import Enum


class ReportItemStatus(str, Enum):
    """Назначение:
        Канонические статусы row-item в report schema v2.
    """

    OK = "OK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ReportContextKey(str, Enum):
    """Назначение:
        Канонические top-level ключи report.context.
    """

    CONFIG = "config"
    INPUT = "input"
    RUNTIME = "runtime"
    REPORT_POLICY = "report_policy"
    STATS = "stats"
    DICTIONARY = "dictionary"
    TARGET_RUNTIME = "target_runtime"
    VAULT_ROLLOUT = "vault_rollout"
    APPLY = "apply"
    APPLY_TARGET = "apply_target"
    CACHE_STATUS = "cache_status"
    CACHE_CLEAR = "cache_clear"
    CACHE_REFRESH = "cache_refresh"
    MAPPING = "mapping"
    NORMALIZE = "normalize"
    ENRICH = "enrich"
    MATCH = "match"
    RESOLVE = "resolve"


class ReportOpKey(str, Enum):
    """Назначение:
        Канонические top-level ключи report.summary.ops.
    """

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    PLAN = "plan"
    APPLY_FAILED = "apply_failed"
    CACHE_REFRESH = "cache_refresh"
    RESOLVE_EXPIRED = "resolve_expired"
    RESOLVE_MAX_ATTEMPTS = "resolve_max_attempts"
    RESOLVE_PENDING = "resolve_pending"


def normalize_context_key(name: ReportContextKey | str) -> str:
    """Назначение:
        Привести ключ context к валидному строковому виду.
    """
    if isinstance(name, ReportContextKey):
        return name.value
    key = str(name).strip()
    if not key:
        raise ValueError("Context key must be non-empty")
    return key


def normalize_op_key(name: ReportOpKey | str) -> str:
    """Назначение:
        Привести ключ операции к валидному строковому виду.
    """
    if isinstance(name, ReportOpKey):
        return name.value
    key = str(name).strip()
    if not key:
        raise ValueError("Operation key must be non-empty")
    return key


def normalize_item_status(status: ReportItemStatus | str) -> ReportItemStatus:
    """Назначение:
        Нормализовать статус item к enum report schema v2.
    """
    if isinstance(status, ReportItemStatus):
        return status
    value = str(status).strip().upper()
    try:
        return ReportItemStatus(value)
    except ValueError:
        # Compatibility bridge для legacy delivery-статусов до полной очистки.
        if "SKIP" in value:
            return ReportItemStatus.SKIPPED
        if "FAIL" in value or "ERROR" in value:
            return ReportItemStatus.FAILED
        return ReportItemStatus.OK


__all__ = [
    "ReportContextKey",
    "ReportItemStatus",
    "ReportOpKey",
    "normalize_context_key",
    "normalize_item_status",
    "normalize_op_key",
]
