"""Readiness dependency_tree — оценка usability target topology snapshot-а

Содержит чистый evaluator для target-side readiness/freshness decisions. Он
работает только с уже собранным snapshot и metadata facts из read seam, не
выполняя сам ни cache-reading, ни bootstrap orchestration.

Зона ответственности:
    - Отличать empty snapshot от freshness degradation
    - Применять policy `none|max_age|revision_required`
    - Возвращать diagnostics в `DiagnosticStage.TOPOLOGY_BOOTSTRAP`

Вне области ответственности:
    - Чтение hierarchy из SQLite/cache
    - Сборка snapshot-а из adjacency rows
    - Command-level short-circuit и DI wiring
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from connector.domain.dependency_tree.snapshot import TopologySnapshot
from connector.domain.diagnostics import build_error, build_warning
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage
from connector.domain.ports.topology.models import (
    TargetHierarchyReadMeta,
    TopologyFreshnessPolicy,
    TopologyTargetReadinessResult,
)


class TopologyTargetReadinessEvaluator:
    """Оценить, пригоден ли target snapshot для topology-aware runtime path

    Границы:
        - Не читает topology сам и не знает о конкретном storage backend.
        - Различает required и optional topology только через severity/decision результата.
    """

    def __init__(
        self,
        *,
        catalog: ErrorCatalog,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._now_provider = now_provider or _utc_now

    def evaluate(
        self,
        *,
        snapshot: TopologySnapshot,
        metadata: TargetHierarchyReadMeta,
        policy: TopologyFreshnessPolicy,
        require_target_topology: bool,
        now: datetime | None = None,
    ) -> TopologyTargetReadinessResult:
        """Вернуть readiness outcome для уже построенного target snapshot-а"""

        resolved_now = _coerce_utc_datetime(now or self._now_provider())
        base_details = {
            "policy_mode": policy.mode,
            "require_target_topology": require_target_topology,
            "row_count": metadata.row_count,
            "cache_snapshot_revision": metadata.cache_snapshot_revision,
            "refreshed_at": (
                metadata.refreshed_at.isoformat()
                if metadata.refreshed_at is not None
                else None
            ),
        }
        if not snapshot.nodes_by_id:
            return self._degraded(
                code="TOPOLOGY_TARGET_EMPTY",
                reason="snapshot_empty",
                require_target_topology=require_target_topology,
                details=base_details,
            )

        freshness_violation = _evaluate_freshness(
            metadata=metadata,
            policy=policy,
            now=resolved_now,
        )
        if freshness_violation is not None:
            reason, extra_details = freshness_violation
            return self._degraded(
                code="TOPOLOGY_TARGET_STALE",
                reason=reason,
                require_target_topology=require_target_topology,
                details={**base_details, **extra_details},
            )

        return TopologyTargetReadinessResult(
            is_ready=True,
            errors=(),
            warnings=(),
            details={
                **base_details,
                "decision": "ready",
                "reason": "ready",
                "freshness_present": _freshness_present(metadata),
            },
        )

    def _degraded(
        self,
        *,
        code: str,
        reason: str,
        require_target_topology: bool,
        details: dict[str, object],
    ) -> TopologyTargetReadinessResult:
        item = _build_diag(
            catalog=self._catalog,
            code=code,
            require_target_topology=require_target_topology,
            details={
                **details,
                "reason": reason,
            },
        )
        result_details = {
            **details,
            "reason": reason,
            "decision": (
                "required_failure"
                if require_target_topology
                else "optional_skip"
            ),
            "freshness_present": _freshness_present_from_details(details),
        }
        if require_target_topology:
            return TopologyTargetReadinessResult(
                is_ready=False,
                errors=(item,),
                warnings=(),
                details=result_details,
            )
        return TopologyTargetReadinessResult(
            is_ready=False,
            errors=(),
            warnings=(item,),
            details=result_details,
        )


def _evaluate_freshness(
    *,
    metadata: TargetHierarchyReadMeta,
    policy: TopologyFreshnessPolicy,
    now: datetime,
) -> tuple[str, dict[str, object]] | None:
    if _revision_required(policy) and metadata.cache_snapshot_revision is None:
        return "missing_cache_snapshot_revision", {}

    if policy.mode == "none":
        return None

    if policy.mode == "revision_required":
        return None

    if metadata.refreshed_at is None:
        return "missing_refreshed_at", {}

    refreshed_at = _coerce_utc_datetime(metadata.refreshed_at)
    age_seconds = int((now - refreshed_at).total_seconds())
    if age_seconds > int(policy.max_age_seconds or 0):
        return (
            "max_age_exceeded",
            {
                "age_seconds": age_seconds,
                "max_age_seconds": policy.max_age_seconds,
            },
        )
    return None


def _build_diag(
    *,
    catalog: ErrorCatalog,
    code: str,
    require_target_topology: bool,
    details: dict[str, object],
) -> DiagnosticItem:
    if require_target_topology:
        return build_error(
            catalog=catalog,
            stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
            code=code,
            details=details,
        )
    return build_warning(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code=code,
        details=details,
        severity=DiagnosticSeverity.WARNING,
    )


def _revision_required(policy: TopologyFreshnessPolicy) -> bool:
    return policy.mode == "revision_required" or policy.require_revision


def _freshness_present(metadata: TargetHierarchyReadMeta) -> bool:
    return (
        metadata.cache_snapshot_revision is not None
        or metadata.refreshed_at is not None
    )


def _freshness_present_from_details(details: dict[str, object]) -> bool:
    return bool(
        details.get("cache_snapshot_revision") is not None
        or details.get("refreshed_at") is not None
    )


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
