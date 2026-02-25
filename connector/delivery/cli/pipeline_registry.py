"""
Назначение:
    Typed factory functions и StageFactory registry для сборки pipeline.

    В delivery layer (не domain) сосредоточена:
    - типобезопасность сборки pipeline;
    - регистрация всех 6 stage descriptors.

Граница ответственности:
    - Owns: typed factory functions, stage descriptor registration.
    - Does NOT: создавать StageExecutionContext, загружать DSL, управлять lifecycle.
    - Does NOT: содержать бизнес-логику — только wiring stage → orchestrator/factory.

Использование:
    build_stage_factory() — из PipelineContainer (DEC-004).

Примечание по match/resolve/resolve_context:
    MatchStage, ResolveStage и ResolveContextStage регистрируются для introspection.
    В production создаются напрямую в PipelineContainer как Singleton (требуют
    дополнительных зависимостей: batch_settings / batch_index).
    Stub-функции намеренно бросают NotImplementedError.
"""

from __future__ import annotations

from connector.domain.ports.cache.roles import EnrichLookupPort, MatchRuntimePort
from connector.domain.transform.context import StageExecutionContext
from connector.domain.transform.enrich.enricher_engine import EnricherEngine
from connector.domain.transform.factory import StageDescriptor, StageFactory
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform.normalize import NormalizerEngine
from connector.domain.transform.resolver.resolve_engine import ResolveEngine
from connector.domain.transform.stages.stages import (
    AnyStageContract,
    EnrichStage,
    MapStage,
    MatchStage,
    NormalizeStage,
    ResolveContextStage,
    ResolveStage,
)


# ── Stage Factory ──────────────────────────────────────────────────────────────


def _map_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> MapperEngine:
    return MapperEngine(
        spec,  # type: ignore[arg-type]
        catalog=ctx.metadata.catalog,
        sink_spec=ctx.metadata.sink_spec,
        options=kwargs.get("options"),  # type: ignore[arg-type]
    )


def _normalize_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> NormalizerEngine:
    return NormalizerEngine(
        spec,  # type: ignore[arg-type]
        catalog=ctx.metadata.catalog,
        sink_spec=ctx.metadata.sink_spec,
        row_builder=kwargs.get("row_builder"),
        options=kwargs.get("options"),  # type: ignore[arg-type]
    )


def _enrich_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> EnricherEngine:
    return EnricherEngine(
        spec=spec,  # type: ignore[arg-type]
        ctx=ctx,
        options=kwargs.get("options"),  # type: ignore[arg-type]
        providers=kwargs.get("gateway"),  # type: ignore[arg-type]
    )


def _match_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> MatchEngine:
    return MatchEngine(
        spec=spec,  # type: ignore[arg-type]
        ctx=ctx,
        resolve_rules=kwargs["resolve_rules"],  # type: ignore[arg-type]
        include_deleted=kwargs.get("include_deleted", False),  # type: ignore[arg-type]
        options=kwargs.get("options"),  # type: ignore[arg-type]
        dedup_store=kwargs.get("dedup_store"),  # type: ignore[arg-type]
    )


def _resolve_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> ResolveEngine:
    return ResolveEngine(
        spec=spec,  # type: ignore[arg-type]
        ctx=ctx,
        options=kwargs.get("options"),  # type: ignore[arg-type]
        codec=kwargs["codec"],  # type: ignore[arg-type]
    )


def _match_stage_stub_wrapper(
    engine: object, ctx: StageExecutionContext,
) -> MatchStage:
    """Stub. MatchStage создаётся напрямую в PipelineContainer (требует batch_settings)."""
    raise NotImplementedError("match is created directly in PipelineContainer, not via StageFactory")


def _resolve_stage_stub_wrapper(
    engine: object, ctx: StageExecutionContext,
) -> ResolveStage:
    """Stub. ResolveStage создаётся напрямую в PipelineContainer (требует batch_index)."""
    raise NotImplementedError("resolve is created directly in PipelineContainer, not via StageFactory")


def _resolve_context_stub_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> None:
    """Stub. ResolveContextStage создаётся напрямую в PipelineContainer, не через StageFactory."""
    raise NotImplementedError("resolve_context is created directly in PipelineContainer, not via StageFactory")


def _resolve_context_stub_wrapper(
    engine: object, ctx: StageExecutionContext,
) -> ResolveContextStage:
    """Stub. ResolveContextStage создаётся напрямую в PipelineContainer, не через StageFactory."""
    raise NotImplementedError("resolve_context is created directly in PipelineContainer, not via StageFactory")


def _stage_wrapper(
    stage_cls: type,
) -> callable:
    """Create a stage wrapper that instantiates stage_cls(engine, catalog)."""
    def wrapper(engine: object, ctx: StageExecutionContext) -> AnyStageContract:
        return stage_cls(engine, ctx.metadata.catalog)  # type: ignore[call-arg]
    return wrapper


def build_stage_factory() -> StageFactory:
    """
    Назначение:
        Создать StageFactory с зарегистрированными 6 стадиями.

    Регистрация дескрипторов — ответственность delivery layer.
    StageFactory (domain) хранит только registry и create() логику.

    Примечание:
        match, resolve, resolve_context — зарегистрированы для introspection (registered_types).
        В production создаются напрямую в PipelineContainer (требуют дополнительных
        зависимостей: batch_settings / batch_index). Вызов create() бросает NotImplementedError.
    """
    factory = StageFactory()

    factory.register(StageDescriptor(
        stage_type="map",
        engine_factory=_map_engine_factory,
        stage_wrapper=_stage_wrapper(MapStage),
        required_capabilities=frozenset(),
    ))

    factory.register(StageDescriptor(
        stage_type="normalize",
        engine_factory=_normalize_engine_factory,
        stage_wrapper=_stage_wrapper(NormalizeStage),
        required_capabilities=frozenset(),
    ))

    factory.register(StageDescriptor(
        stage_type="enrich",
        engine_factory=_enrich_engine_factory,
        stage_wrapper=_stage_wrapper(EnrichStage),
        required_capabilities=frozenset({EnrichLookupPort}),
    ))

    factory.register(StageDescriptor(
        stage_type="match",
        engine_factory=_match_engine_factory,
        # Wrapper не используется: MatchStage создаётся напрямую в PipelineContainer
        # (требует batch_settings: IMatchBatchSettings — недоступен через _stage_wrapper).
        stage_wrapper=_match_stage_stub_wrapper,
        required_capabilities=frozenset({MatchRuntimePort}),
    ))

    factory.register(StageDescriptor(
        stage_type="resolve",
        engine_factory=_resolve_engine_factory,
        # Wrapper не используется: ResolveStage создаётся напрямую в PipelineContainer
        # (требует batch_index: IBatchIndexService — недоступен через _stage_wrapper).
        stage_wrapper=_resolve_stage_stub_wrapper,
        required_capabilities=frozenset(),
    ))

    factory.register(StageDescriptor(
        stage_type="resolve_context",
        engine_factory=_resolve_context_stub_factory,
        stage_wrapper=_resolve_context_stub_wrapper,
        required_capabilities=frozenset(),
    ))

    return factory
