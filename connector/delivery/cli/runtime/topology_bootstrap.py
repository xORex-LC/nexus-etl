"""Runtime step topology bootstrap — pre-handler activation, short-circuit и binding.

Этот модуль живёт в delivery runtime, потому что знает о command context,
report sink и container wiring. Само построение topology artifacts остаётся в
use case слое; runtime step только:

1. разрешает dataset и activation decision;
2. собирает конкретные adapters/factories из DI container;
3. публикует report context;
4. решает, вызывать ли handler дальше.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from connector.delivery.cli.containers import build_diagnostics_catalog
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.domain.dependency_tree import (
    TargetHierarchyTopologyBuilder,
    TopologyTargetReadinessEvaluator,
)
from connector.domain.diagnostics import build_error
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent
from connector.domain.transform_dsl import (
    load_mapping_spec_for_dataset,
    load_source_spec_for_dataset,
    resolve_source_location,
)
from connector.infra.logging.topology import LegacyLogEventSink
from connector.infra.topology import (
    PolarsSourceAdjacencyReader,
    SqliteTopologyTargetMembershipReader,
    SqliteTopologyTargetReader,
)
from connector.usecases.topology_bootstrap import (
    StaticTopologyProvider,
    TopologyBootstrapUseCase,
    TopologyRequirementResolver,
    TopologyRuntimeBinding,
    TraceToSink,
)
from connector.usecases.topology_source_validation import SourceTopologyValidationUseCase
from connector.usecases.topology_target_build import TargetTopologyBuildUseCase


@dataclass(frozen=True)
class TopologyBootstrapStepResult:
    """Итог pre-handler topology bootstrap шага."""

    requirements: Requirements
    runtime_binding: TopologyRuntimeBinding | None
    command_result: CommandResult | None

    @classmethod
    def inactive(cls, requirements: Requirements) -> "TopologyBootstrapStepResult":
        """Skip-результат для команд без активного topology bootstrap.

        Сохраняет единый контракт результата (включая `requirements`), чтобы
        вызывающий код не натыкался на разные формы и не получал AttributeError.
        """
        return cls(requirements=requirements, runtime_binding=None, command_result=None)


class TopologyBootstrapStep:
    """Запустить topology bootstrap до handler logic и подготовить runtime binding."""

    def __init__(self, *, requirement_resolver: TopologyRequirementResolver | None = None) -> None:
        self._requirement_resolver = requirement_resolver or TopologyRequirementResolver()

    def run(
        self,
        *,
        ctx: UnboundCommandContext,
        command_name: str,
        dataset_name: str,
        requirements: Requirements,
        container,
        report_sink,
        logger: logging.Logger,
        run_id: str,
    ) -> TopologyBootstrapStepResult:
        catalog = build_diagnostics_catalog(
            dataset_name,
            strict=ctx.app_config.observability.diagnostics.strict,
        )
        decision = self._requirement_resolver.resolve(
            command_name=command_name,
            dataset_name=dataset_name,
        )
        request = replace(decision.request, run_id=run_id)
        resolved_requirements = replace(
            requirements,
            requires_source_topology=request.require_source_topology,
            requires_target_topology=request.require_target_topology,
        )

        if decision.activation_error is not None:
            # Конфликт конфигурации: consumer policy включена, но topology capability
            # выключена. Ловим рано, единой catalog-диагностикой, вместо сырого ValueError
            # на поздней сборке resolve/match-стадии.
            event_sink = LegacyLogEventSink(logger=logger, run_id=run_id)
            diagnostic = build_error(
                catalog=catalog,
                stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                code="TOPOLOGY_CAPABILITY_DISABLED",
                message=decision.activation_error,
            )
            binding = TopologyRuntimeBinding(
                provider=None,
                request=request,
                artifacts=None,
                errors=(diagnostic,),
                warnings=(),
                activation_sources=decision.activation_sources,
            )
            report_sink.emit(
                SetContextEvent(
                    name=ReportContextKey.TOPOLOGY,
                    value=binding.report_context_payload(),
                )
            )
            event_sink.emit(
                level=logging.ERROR,
                event="bootstrap.short_circuit",
                payload={"diag_code": diagnostic.code, "reason": "capability_disabled"},
            )
            command_result = CommandResult()
            command_result.add_diagnostics((diagnostic,), catalog)
            return TopologyBootstrapStepResult(
                requirements=resolved_requirements,
                runtime_binding=binding,
                command_result=command_result,
            )

        if not decision.activated:
            binding = TopologyRuntimeBinding(
                provider=None,
                request=request,
                artifacts=None,
                errors=(),
                warnings=(),
                activation_sources=decision.activation_sources,
                skipped_reason=decision.skipped_reason or "not_required",
            )
            event_sink = LegacyLogEventSink(logger=logger, run_id=run_id)
            event_sink.emit(
                level=logging.DEBUG,
                event="bootstrap.skipped",
                payload={
                    "reason": binding.skipped_reason,
                    "dataset": dataset_name,
                },
            )
            report_sink.emit(
                SetContextEvent(
                    name=ReportContextKey.TOPOLOGY,
                    value=binding.report_context_payload(),
                )
            )
            return TopologyBootstrapStepResult(
                requirements=resolved_requirements,
                runtime_binding=binding,
                command_result=None,
            )

        event_sink = LegacyLogEventSink(logger=logger, run_id=run_id)
        usecase = TopologyBootstrapUseCase(
            target_usecase_factory=lambda topology_spec, compiled: _build_target_usecase(
                container=container,
                catalog=catalog,
                event_sink=event_sink,
                topology_spec=topology_spec,
                compiled=compiled,
            ),
            source_validation_usecase_factory=lambda topology_spec, compiled: (
                _build_source_validation_usecase(
                    container=container,
                    catalog=catalog,
                    topology_spec=topology_spec,
                )
            ),
            event_sink=event_sink,
        )
        command_result = None
        try:
            result = usecase.run(
                request=request,
                target_failure_is_hard=decision.target_failure_is_hard,
            )
        except _TopologyBootstrapConfigurationError as exc:
            binding = TopologyRuntimeBinding(
                provider=None,
                request=request,
                artifacts=None,
                errors=(exc.diagnostic,),
                warnings=(),
                activation_sources=decision.activation_sources,
            )
            report_sink.emit(
                SetContextEvent(
                    name=ReportContextKey.TOPOLOGY,
                    value=binding.report_context_payload(),
                )
            )
            event_sink.emit(
                level=logging.ERROR,
                event="bootstrap.short_circuit",
                payload={
                    "diag_code": exc.diagnostic.code,
                    "side": "target",
                },
            )
            command_result = CommandResult()
            command_result.add_diagnostics((exc.diagnostic,), catalog)
            return TopologyBootstrapStepResult(
                requirements=resolved_requirements,
                runtime_binding=binding,
                command_result=command_result,
            )
        provider = None
        if result.artifacts is not None:
            provider = StaticTopologyProvider(
                source_snapshot=result.artifacts.source_snapshot,
                target_snapshot=result.artifacts.target_snapshot,
            )

        binding = TopologyRuntimeBinding(
            provider=provider,
            request=request,
            artifacts=result.artifacts,
            errors=result.errors,
            warnings=result.warnings,
            activation_sources=decision.activation_sources,
        )
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.TOPOLOGY,
                value=binding.report_context_payload(),
            )
        )

        if result.errors:
            event_sink.emit(
                level=logging.ERROR,
                event="bootstrap.short_circuit",
                payload={
                    "diag_code": result.errors[0].code,
                    "side": "target",
                },
            )
            command_result = CommandResult()
            command_result.add_diagnostics(
                (*result.errors, *result.warnings),
                catalog,
            )

        return TopologyBootstrapStepResult(
            requirements=resolved_requirements,
            runtime_binding=binding,
            command_result=command_result,
        )


def attach_topology_runtime(
    *,
    ctx: UnboundCommandContext,
    runtime_binding: TopologyRuntimeBinding | None,
) -> UnboundCommandContext:
    """Вернуть новый command context с topology runtime binding в `extra`."""

    if runtime_binding is None:
        return ctx
    extra = dict(ctx.extra or {})
    extra["topology_runtime"] = runtime_binding
    return CommandContext(
        logger=ctx.logger,
        run_id=ctx.run_id,
        catalog=ctx.catalog,
        strict=ctx.strict,
        app_config=ctx.app_config,
        container=ctx.container,
        paths=ctx.paths,
        extra=extra,
    )


def _build_target_usecase(
    *,
    container,
    catalog,
    event_sink,
    topology_spec,
    compiled,
) -> TargetTopologyBuildUseCase:
    cache_bundle = container.cache_dsl()
    cache_read = container.cache.roles().topology_read
    cache_spec = _require_cache_spec(
        cache_specs=cache_bundle.cache_specs,
        topology_dataset=topology_spec.dataset,
        catalog=catalog,
    )
    trace = TraceToSink.from_sink(sink=event_sink, namespace="target")
    reader = SqliteTopologyTargetReader(
        cache_read=cache_read,
        cache_spec=cache_spec,
        node_id_field=topology_spec.topology.target.node_id_field,
        parent_id_field=topology_spec.topology.target.parent_id_field,
        target_label_field=topology_spec.topology.target.target_label_field,
        payload_target_id_field=topology_spec.topology.target.payload_target_id_field,
        canonicalizer=compiled.python,
    )
    builder = TargetHierarchyTopologyBuilder(
        catalog=catalog,
        trace=trace,
    )
    readiness = TopologyTargetReadinessEvaluator(catalog=catalog)
    event_sink.emit(
        level=logging.INFO,
        event="target.build.start",
        payload={
            "node_id_field": topology_spec.topology.target.node_id_field,
            "parent_id_field": topology_spec.topology.target.parent_id_field,
            "target_label_field": topology_spec.topology.target.target_label_field,
        },
    )
    return TargetTopologyBuildUseCase(
        reader=reader,
        builder=builder,
        readiness_evaluator=readiness,
    )


def _build_source_validation_usecase(
    *,
    container,
    catalog,
    topology_spec,
) -> SourceTopologyValidationUseCase:
    source_topology = _require_source_adjacency_spec(
        source_spec=topology_spec.topology.source,
        catalog=catalog,
        topology_dataset=topology_spec.dataset,
    )
    source_spec = load_source_spec_for_dataset(topology_spec.dataset)
    csv_options = source_spec.source.csv_options()
    cache_bundle = container.cache_dsl()
    cache_read = container.cache.roles().topology_read
    cache_spec = _require_cache_spec(
        cache_specs=cache_bundle.cache_specs,
        topology_dataset=topology_spec.dataset,
        catalog=catalog,
    )
    source_reader = PolarsSourceAdjacencyReader(
        path=resolve_source_location(source_spec),
        has_header=source_spec.source.has_header,
        delimiter=csv_options.delimiter,
        encoding=csv_options.encoding,
        node_id_field=source_topology.node_id_field,
        parent_id_field=source_topology.parent_id_field,
        label_field=source_topology.label_field,
    )
    membership_reader = SqliteTopologyTargetMembershipReader(
        cache_read=cache_read,
        cache_spec=cache_spec,
        membership_field=source_topology.target_membership_field,
    )
    return SourceTopologyValidationUseCase(
        source_reader=source_reader,
        target_membership_reader=membership_reader,
        catalog=catalog,
        pipeline_node_id_field=_mapped_field_for_source(
            dataset=topology_spec.dataset,
            source_field=source_topology.node_id_field,
        ),
    )


@dataclass(frozen=True)
class _TopologyBootstrapConfigurationError(Exception):
    """Bootstrap configuration error already translated into a diagnostic."""

    diagnostic: DiagnosticItem


def _require_cache_spec(
    *,
    cache_specs,
    topology_dataset: str,
    catalog,
):
    for spec in cache_specs:
        if spec.dataset == topology_dataset:
            return spec
    diagnostic = build_error(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_TARGET_CACHE_SPEC_MISSING",
        field=None,
        message=(
            "Target topology cache spec is missing for topology dataset "
            f"'{topology_dataset}'"
        ),
        record_ref=None,
        details={"topology_dataset": topology_dataset},
    )
    raise _TopologyBootstrapConfigurationError(diagnostic=diagnostic)


def _require_source_adjacency_spec(
    *,
    source_spec,
    catalog,
    topology_dataset: str,
):
    if getattr(source_spec, "mode", None) == "adjacency_list":
        return source_spec
    diagnostic = build_error(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_DSL_SPEC_INVALID",
        field="topology.source.mode",
        message=(
            "Source topology validation requires adjacency_list source mode "
            f"for topology dataset '{topology_dataset}'"
        ),
        details={
            "topology_dataset": topology_dataset,
            "source_mode": getattr(source_spec, "mode", None),
        },
    )
    raise _TopologyBootstrapConfigurationError(diagnostic=diagnostic)


def _mapped_field_for_source(*, dataset: str, source_field: str) -> str:
    mapping_spec = load_mapping_spec_for_dataset(dataset)
    for rule in mapping_spec.mapping.rules:
        if rule.source != source_field:
            continue
        if rule.target is not None:
            return rule.target
        if rule.targets:
            return rule.targets[0]
    return source_field
