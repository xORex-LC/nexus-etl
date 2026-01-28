from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from connector.common.sanitize import maskSecretsInObject
from connector.domain.models import DiagnosticStage, MatchStatus, RowRef, ValidationErrorItem
from connector.domain.planning.match_models import MatchedRow
from connector.domain.planning.resolver import Resolver
from connector.domain.transform.result import TransformResult


class ResolveUseCase:
    """
    Назначение/ответственность:
        Use-case разрешения операций (match -> resolve).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_resolved_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_resolved_items = include_resolved_items

    def iter_resolved_ok(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
        *,
        dataset: str | None = None,
    ):
        """
        Назначение:
            Итератор разрешённых строк без ошибок (для plan).
        """
        for resolved in self._iter_resolved(matched_source, resolver, dataset=dataset):
            if resolved.errors:
                continue
            yield resolved

    def run(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
        dataset: str,
        report,
    ) -> int:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        _report_expired(report, resolver.drain_expired(), resolver.settings)
        for resolved in self._iter_resolved(matched_source, resolver, dataset=dataset):
            row = resolved.row
            if row is None:
                status = _resolve_status(resolved)
                if status is None:
                    continue
                _count_special_ops(report, resolved.errors, resolved.warnings)
                report.add_item(
                    status=status,
                    row_ref=resolved.row_ref,
                    payload=None,
                    errors=resolved.errors,
                    warnings=resolved.warnings,
                    meta={"op": None},
                    store=True,
                )
                continue
            status = "FAILED" if resolved.errors else "OK"
            payload = asdict(row) if self.include_resolved_items and row is not None else None
            _count_special_ops(report, resolved.errors, resolved.warnings)
            report.add_item(
                status=status,
                row_ref=row.row_ref if row else None,
                payload=maskSecretsInObject(payload) if payload else None,
                errors=resolved.errors,
                warnings=resolved.warnings,
                meta={"op": row.op if row else None},
                store=status == "FAILED" or self.include_resolved_items,
            )
            _report_expired(report, resolver.drain_expired(), resolver.settings)
        _purge_pending(resolver)
        return 1 if report.summary.errors_total > 0 else 0

    def _iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
        *,
        dataset: str | None = None,
    ):
        matched_rows: list[TransformResult[MatchedRow]] = []
        for matched in matched_source:
            matched_rows.append(matched)

        batch_index = _build_batch_index(matched_rows, resolver, dataset)
        resource_id_map = _build_resource_id_map(matched_rows)

        for matched in matched_rows:
            if matched.row is None:
                yield matched  # type: ignore[return-value]
                continue
            resolved_row, errors, warnings = resolver.resolve(
                matched.row,
                resource_id_map=resource_id_map,
                meta=matched.meta,
                batch_index=batch_index,
            )
            yield TransformResult(
                record=matched.record,
                row=resolved_row,
                row_ref=matched.row_ref,
                match_key=matched.match_key,
                meta=matched.meta,
                secret_candidates=matched.secret_candidates,
                errors=errors,
                warnings=warnings,
            )


def _build_resource_id_map(matched_rows: list[TransformResult[MatchedRow]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in matched_rows:
        row = item.row
        if row is None:
            continue
        if row.match_status == MatchStatus.MATCHED and row.existing:
            resource_id = row.existing.get("_id")
        else:
            resource_id = row.resource_id
        if resource_id:
            mapping[row.identity.primary_value] = str(resource_id)
    return mapping


def _build_batch_index(
    matched_rows: list[TransformResult[MatchedRow]],
    resolver: Resolver,
    dataset: str | None,
) -> dict[str, dict[str, list[str]]]:
    if dataset is None:
        return {}
    return resolver.build_batch_index(matched_rows, dataset)


def _purge_pending(resolver: Resolver) -> None:
    # Чистим обработанные pending-записи по retention, если включено.
    settings = resolver.settings
    if settings is None:
        return
    if settings.pending_retention_days <= 0:
        return
    if resolver.pending_repo is None:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.pending_retention_days)
    resolver.pending_repo.purge_stale(cutoff.isoformat())


def _resolve_status(item: TransformResult) -> str | None:
    if item.errors:
        return "FAILED"
    for warning in item.warnings:
        if warning.code == "RESOLVE_PENDING":
            return "PENDING"
    return None


def _report_expired(report, expired, settings) -> None:
    mode = getattr(settings, "pending_on_expire", "error") if settings is not None else "error"
    if mode == "skip":
        return
    for item in expired:
        error = ValidationErrorItem(
            stage=DiagnosticStage.RESOLVE,
            code="RESOLVE_EXPIRED",
            field=item.field,
            message=item.reason or "pending link expired",
        )
        if mode == "report_only":
            report.add_item(
                status="OK",
                row_ref=RowRef(
                    line_no=0,
                    row_id=item.source_row_id,
                    identity_primary=None,
                    identity_value=None,
                ),
                payload=None,
                errors=[],
                warnings=[error],
                meta={
                    "pending_id": item.pending_id,
                    "lookup_key": item.lookup_key,
                },
                store=True,
            )
            report.add_op("resolve_expired", ok=1, count=1)
            continue
        report.add_item(
            status="FAILED",
            row_ref=RowRef(
                line_no=0,
                row_id=item.source_row_id,
                identity_primary=None,
                identity_value=None,
            ),
            payload=None,
            errors=[error],
            warnings=[],
            meta={
                "pending_id": item.pending_id,
                "lookup_key": item.lookup_key,
            },
            store=True,
        )
        report.add_op("resolve_expired", failed=1, count=1)


def _count_special_ops(report, errors, warnings) -> None:
    if any(err.code == "RESOLVE_MAX_ATTEMPTS" for err in errors or []):
        report.add_op("resolve_max_attempts", failed=1, count=1)
    if any(warn.code == "RESOLVE_PENDING" for warn in warnings or []):
        report.add_op("resolve_pending", ok=1, count=1)
