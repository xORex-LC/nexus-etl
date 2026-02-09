from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.transform.core.iterators import iter_micro_batches
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.result_processor import PlanningResultProcessor
from connector.domain.transform.stages.stages import ResolveStage


class ResolveUseCase:
    """
    Назначение/ответственность:
        Use-case разрешения операций (match -> resolve).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_resolved_items: bool,
        batch_size: int = 500,
        flush_interval_ms: int = 500,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_resolved_items = include_resolved_items
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms

    def iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolve_stage: ResolveStage,
        *,
        dataset: str | None = None,
    ):
        """
        Назначение:
            Итератор разрешённых строк (для plan).
        """
        return self._iter_resolved(matched_source, resolve_stage, dataset=dataset)

    def run(
        self,
        matched_source: Iterable[TransformResult],
        resolve_stage: ResolveStage,
        dataset: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        resolver = resolve_stage.resolver
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

        for resolved in self._iter_resolved(matched_source, resolve_stage, dataset=dataset):
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
        resolve_stage: ResolveStage,
        *,
        dataset: str | None = None,
    ):
        for batch in iter_micro_batches(
            matched_source,
            batch_size=self.batch_size,
            flush_interval_ms=self.flush_interval_ms,
        ):
            for resolved in resolve_stage.run(batch, dataset=dataset):
                yield resolved


def _purge_pending(resolver) -> None:
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
        diag = (diag_warning if mode == "report_only" else diag_error)(
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
        report_errors, report_warnings = split_report_diagnostics(
            [] if mode == "report_only" else [diag],
            [diag] if mode == "report_only" else [],
        )
        if mode == "report_only":
            report.add_item(
                status="OK",
                row_ref=diag.record_ref,
                payload=None,
                errors=report_errors,
                warnings=report_warnings,
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
            row_ref=diag.record_ref,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
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
