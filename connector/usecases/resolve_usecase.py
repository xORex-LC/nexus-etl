from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from connector.domain.models import DiagnosticStage, MatchStatus, RowRef
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.lookup_enricher import LookupEnricher
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.transform.result_processor import PlanningResultProcessor
from connector.domain.transform.stages import ResolveStage


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

    def iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolver: LookupEnricher,
        *,
        dataset: str | None = None,
        catalog: ErrorCatalog,
    ):
        """
        Назначение:
            Итератор разрешённых строк (для plan).
        """
        return self._iter_resolved(matched_source, resolver, dataset=dataset, catalog=catalog)

    def run(
        self,
        matched_source: Iterable[TransformResult],
        resolver: LookupEnricher,
        dataset: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        _report_expired(report, resolver.drain_expired(), resolver.settings, catalog)
        processor = PlanningResultProcessor(
            report=report,
            include_items=self.include_resolved_items,
            context_key="resolve",
            ok_label="resolved_ok",
            failed_label="resolve_failed",
            meta_builder=lambda r: {"op": r.row.op if r.row else None},
            should_skip=lambda r: _resolve_status(r) is None and r.row is None,
        )

        for resolved in self._iter_resolved(matched_source, resolver, dataset=dataset, catalog=catalog):
            _count_special_ops(report, resolved.errors, resolved.warnings)
            processor.process(resolved)
            _report_expired(report, resolver.drain_expired(), resolver.settings, catalog)
        _purge_pending(resolver)
        result = processor.finalize()
        if report.summary.errors_total > 0:
            result.add_code(SystemErrorCode.CONFLICT)
        return result

    def _iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolver: LookupEnricher,
        *,
        dataset: str | None = None,
        catalog: ErrorCatalog,
    ):
        stage = ResolveStage(resolver, catalog)
        for resolved in stage.run(matched_source, dataset=dataset):
            yield resolved


def _purge_pending(resolver: LookupEnricher) -> None:
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


def _report_expired(report, expired, settings, catalog: ErrorCatalog) -> None:
    mode = getattr(settings, "pending_on_expire", "error") if settings is not None else "error"
    if mode == "skip":
        return
    for item in expired:
        error = diag_error(
            catalog=catalog,
            stage=DiagnosticStage.RESOLVE,
            code="RESOLVE_EXPIRED",
            field=item.field,
            message=item.reason or "pending link expired",
            record_ref=RowRef(
                line_no=0,
                row_id=item.source_row_id,
                identity_primary=None,
                identity_value=None,
            ),
        )
        if mode == "report_only":
            report.add_item(
                status="OK",
                row_ref=error.record_ref,
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
            row_ref=error.record_ref,
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
