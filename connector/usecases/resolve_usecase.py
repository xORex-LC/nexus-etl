from __future__ import annotations

import structlog
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from itertools import chain
from typing import Iterable

from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, ReportOpKey
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import PlanningStageReportStrategy
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.events import AddItemEvent, AddOpEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import IReportSink
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.ports.cache.roles import ResolveRuntimePort
from connector.domain.transform.core.iterators import iter_micro_batches
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.resolver import pending_codec
from connector.domain.transform.resolver.ports import IPendingExpiryService
from connector.domain.transform.stages.stages import PipelineHooks, PipelineOrchestrator, ResolveStage

logger = structlog.get_logger(__name__)


class ResolveUseCase:
    """
    Назначение/ответственность:
        Use-case разрешения операций (match -> resolve).

    Граница ответственности:
        - Owns: micro-batching, transaction scope, report aggregation.
        - Does NOT: создавать infra-сервисы (pending expiry/codec) — получает через DI.
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
        pending_replay: ResolveRuntimePort | None = None,
        resolve_hooks: PipelineHooks | None = None,
    ):
        """
        Назначение:
            Итератор разрешённых строк (для plan).

        Параметр ``pending_replay``:
            Если передан вместе с ``dataset``, pending-строки из storage
            десериализуются через ``pending_codec`` и добавляются в конец
            ``matched_source`` перед разрешением.
            ``None`` (по умолчанию) — поведение без изменений.

        Параметр ``resolve_hooks``:
            Lifecycle hooks для micro-batch запуска ``ResolveStage``.
            Используется delivery-layer для housekeeping (например, sweep expired pending).
        """
        pending_rows: list[TransformResult] = []
        if pending_replay is not None and dataset is not None:
            load_result = pending_codec.load_pending_rows(
                pending_replay.list_pending_rows(dataset)
            )
            pending_rows = load_result.rows
            if load_result.skipped > 0:
                logger.warning(
                    "pending_codec_skipped_invalid",
                    count=load_result.skipped,
                    dataset=dataset,
                )
        all_matched = chain(matched_source, pending_rows)
        return self._iter_resolved(all_matched, resolve_stage, resolve_hooks=resolve_hooks)

    def run(
        self,
        matched_source: Iterable[TransformResult],
        resolve_stage: ResolveStage,
        dataset: str,
        report_sink: IReportSink,
        report_policy: ReportPolicy,
        catalog: ErrorCatalog,
        *,
        pending_expiry: IPendingExpiryService,
        resolve_hooks: PipelineHooks,
    ) -> CommandResult:
        """
        Назначение:
            Выполнить resolve-проход с репортингом и lifecycle housekeeping.

        Contract:
            - pending_expiry хранит expired pending между micro-batches.
            - resolve_hooks должен триггерить pending_expiry.sweep() после
              завершения каждого micro-batch resolve-стадии.
        """
        resolver = resolve_stage.resolver
        expired_failures = _report_expired(report_sink, pending_expiry.drain_expired(), resolver.settings, catalog)
        reporter = StageResultReporter(
            sink=report_sink,
            report_policy=report_policy,
            include_items=self.include_resolved_items,
            context_key=ReportContextKey.RESOLVE,
            ok_label="resolved_ok",
            failed_label="resolve_failed",
            strategy=PlanningStageReportStrategy(
                meta_builder=lambda r: {"op": r.row.op if r.row else None},
                should_skip=lambda r: _resolve_status(r) is None and r.row is None,
            ),
            report_stage=DiagnosticStage.RESOLVE,
            include_upstream_diagnostics=False,
        )

        for resolved in self._iter_resolved(
            matched_source,
            resolve_stage,
            resolve_hooks=resolve_hooks,
        ):
            _count_special_ops(report_sink, resolved.errors, resolved.warnings)
            reporter.process(resolved)
            expired_failures += _report_expired(
                report_sink,
                pending_expiry.drain_expired(),
                resolver.settings,
                catalog,
            )
        # Sweep выполняется через resolve_hooks.on_stage_complete после исчерпания
        # micro-batch; отдельный финальный drain нужен, чтобы не потерять последний batch.
        expired_failures += _report_expired(report_sink, pending_expiry.drain_expired(), resolver.settings, catalog)
        _purge_pending(resolver)
        stats = reporter.publish_context()
        has_conflicts = stats.failed_rows > 0 or expired_failures > 0
        return StageCommandResultResolver().resolve(stats, has_conflicts=has_conflicts)

    def _iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolve_stage: ResolveStage,
        *,
        resolve_hooks: PipelineHooks | None = None,
    ):
        """
        Назначение:
            Выполнить resolve в micro-batches с транзакционным scope на батч.

        Алгоритм:
            1. Нарезать поток matched-элементов на micro-batches.
            2. Для каждого батча открыть transaction() runtime-порта (если есть).
            3. Запустить ``ResolveStage`` напрямую или через ``PipelineOrchestrator``
               (если переданы lifecycle hooks).
        """
        batches = iter(
            iter_micro_batches(
                matched_source,
                batch_size=self.batch_size,
                flush_interval_ms=self.flush_interval_ms,
            )
        )
        resolve_segment = (
            PipelineOrchestrator([resolve_stage], hooks=resolve_hooks)
            if resolve_hooks is not None
            else None
        )
        while True:
            with _resolve_transaction(resolve_stage):
                try:
                    batch = next(batches)
                except StopIteration:
                    return
                stage_stream = resolve_segment.run(batch) if resolve_segment is not None else resolve_stage.run(batch)
                for resolved in stage_stream:
                    yield resolved


def _purge_pending(resolver) -> None:
    # Чистим обработанные pending-записи по retention, если включено.
    settings = resolver.settings
    if settings is None:
        return
    if settings.pending_retention_days <= 0:
        return
    if resolver.cache_gateway is None:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.pending_retention_days)
    resolver.cache_gateway.purge_stale(cutoff.isoformat())


def _resolve_status(item: TransformResult) -> str | None:
    if item.errors:
        return "FAILED"
    for warning in item.warnings:
        if warning.code == "RESOLVE_PENDING":
            return "PENDING"
    return None


def _report_expired(report_sink: IReportSink, expired, settings, catalog: ErrorCatalog) -> int:
    mode = getattr(settings, "pending_on_expire", "error") if settings is not None else "error"
    if mode == "skip":
        return 0
    failed_count = 0
    for item in expired:
        diag = (diag_warning if mode == "report_only" else diag_error)(
            catalog=catalog,
            stage=DiagnosticStage.RESOLVE,
            code="RESOLVE_EXPIRED",
            field=item.field,
            message=item.reason or "pending link expired",
            record_ref=RowRef(
                line_no=None,
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
            report_sink.emit(
                AddItemEvent(
                    status=ReportItemStatus.OK,
                    row_ref=diag.record_ref,
                    payload=None,
                    errors=tuple(report_errors),
                    warnings=tuple(report_warnings),
                    meta={
                        "pending_id": item.pending_id,
                        "lookup_key": item.lookup_key,
                    },
                    store=True,
                    preaggregated=False,
                )
            )
            report_sink.emit(AddOpEvent(name=ReportOpKey.RESOLVE_EXPIRED, ok=1, count=1))
            continue
        report_sink.emit(
            AddItemEvent(
                status=ReportItemStatus.FAILED,
                row_ref=diag.record_ref,
                payload=None,
                errors=tuple(report_errors),
                warnings=tuple(report_warnings),
                meta={
                    "pending_id": item.pending_id,
                    "lookup_key": item.lookup_key,
                },
                store=True,
                preaggregated=False,
            )
        )
        report_sink.emit(AddOpEvent(name=ReportOpKey.RESOLVE_EXPIRED, failed=1, count=1))
        failed_count += 1
    return failed_count


def _count_special_ops(report_sink: IReportSink, errors, warnings) -> None:
    if any(err.code == "RESOLVE_MAX_ATTEMPTS" for err in errors or []):
        report_sink.emit(AddOpEvent(name=ReportOpKey.RESOLVE_MAX_ATTEMPTS, failed=1, count=1))
    if any(warn.code == "RESOLVE_PENDING" for warn in warnings or []):
        report_sink.emit(AddOpEvent(name=ReportOpKey.RESOLVE_PENDING, ok=1, count=1))


def _resolve_transaction(resolve_stage: ResolveStage):
    resolver = getattr(resolve_stage, "resolver", None)
    cache_gateway = getattr(resolver, "cache_gateway", None) if resolver is not None else None
    if cache_gateway is None:
        return nullcontext()
    tx = getattr(cache_gateway, "transaction", None)
    if not callable(tx):
        return nullcontext()
    return tx()
