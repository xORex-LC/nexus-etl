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
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent
from connector.infra.logging.topology import LegacyLogEventSink
from connector.infra.topology import SqliteTopologyTargetReader
from connector.usecases.topology_bootstrap import (
    StaticTopologyProvider,
    TopologyBootstrapUseCase,
    TopologyRequirementResolver,
    TopologyRuntimeBinding,
    TraceToSink,
)
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
            strict=ctx.app_config.observability.diagnostics_strict,
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

        if not decision.activated:
            return TopologyBootstrapStepResult(
                requirements=resolved_requirements,
                runtime_binding=None,
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
            event_sink=event_sink,
        )
        result = usecase.run(
            request=request,
            target_failure_is_hard=decision.target_failure_is_hard,
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

        command_result = None
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
            command_result.add_diagnostics(result.errors, catalog)

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
    cache_gateway = container.cache.gateway()
    cache_spec = next(
        spec for spec in cache_bundle.cache_specs if spec.dataset == topology_spec.dataset
    )
    trace = TraceToSink.from_sink(sink=event_sink, namespace="target")
    reader = SqliteTopologyTargetReader(
        cache_gateway=cache_gateway,
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
