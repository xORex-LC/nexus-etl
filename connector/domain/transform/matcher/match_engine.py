"""
Назначение:
    StageEngine-обвязка matcher: MatchSpec -> MatchDsl -> MatchCore.

Граница ответственности:
    - Owns: компиляция MatchSpec → MatchCore; проброс dedup_store.
    - Does NOT: бизнес-логика матчинга (делегирует MatchCore).
    - Does NOT: управление lifecycle dedup_store (делегирует PlanningPipeline).

    Поддерживает два пути инициализации (DEC-004 transition):
    - ctx: StageExecutionContext — новый путь (capabilities из context).
    - scattered params (dataset, cache_gateway, catalog) — legacy путь.

Переходный период (Stage 2 → Stage 4):
    reset_source_dedup() и bind_runtime_scope() оставлены как no-op стабы,
    пока MatchProcessor Protocol и MatchUseCase не обновлены (Stage 4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform_dsl.build_options import MatchDslBuildOptions
from connector.domain.transform_dsl.specs import MatchSpec
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform.matcher.dedup_store import LocalSourceDedupStore
from connector.domain.transform.matcher.ports import ISourceDedupStore
from connector.domain.transform_dsl.compilers.match import MatchDsl
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform_dsl.compilers.resolve import ResolveRules

if TYPE_CHECKING:
    from connector.domain.transform.context import StageExecutionContext


class MatchEngine:
    """
    Назначение/ответственность:
        Тонкая runtime-обвязка match-стадии без бизнес-логики матчинга.

    Поддерживает два пути инициализации (DEC-004 transition):
        - ctx: StageExecutionContext — scoped capabilities (новый путь).
        - dataset/cache_gateway/catalog — scattered params (legacy путь).

    dedup_store:
        Если не передан — создаётся LocalSourceDedupStore() по умолчанию.
        В Stage 4 будет передаваться явно из PipelineRunContext через DI.
    """

    def __init__(
        self,
        *,
        spec: MatchSpec,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        ctx: StageExecutionContext | None = None,
        dataset: str | None = None,
        cache_gateway: MatchRuntimePort | None = None,
        catalog: ErrorCatalog | None = None,
        dsl: MatchDsl | None = None,
        options: MatchDslBuildOptions | None = None,
        dedup_store: ISourceDedupStore | None = None,
    ) -> None:
        if ctx is not None:
            resolved_dataset = ctx.metadata.dataset_name
            resolved_gateway = ctx.require(MatchRuntimePort)
            resolved_catalog = ctx.metadata.catalog
        else:
            resolved_dataset = dataset or ""
            resolved_gateway = cache_gateway  # type: ignore[assignment]
            resolved_catalog = catalog or ErrorCatalog(dataset=resolved_dataset, items={})

        self.dsl = dsl or MatchDsl(options=options)
        self.matching_rules = self.dsl.compile(spec)
        self.core = MatchCore(
            dataset=resolved_dataset,
            cache_gateway=resolved_gateway,
            matching_rules=self.matching_rules,
            resolve_rules=resolve_rules,
            include_deleted=include_deleted,
            catalog=resolved_catalog,
            dedup_store=dedup_store or LocalSourceDedupStore(),
        )

    def match(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        return self.core.match(enriched)

    def match_with_source_dedup(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        return self.core.match_with_source_dedup(enriched)

    def match_stream(self, enriched_source):
        return self.core.match_stream(enriched_source)

    def reset_source_dedup(self) -> None:
        """
        No-op stub. Lifecycle reset теперь в PlanningPipeline через dedup_store.reset().
        Оставлен для совместимости с MatchProcessor Protocol до Stage 4.
        """

    def bind_runtime_scope(self, scope: str | None) -> None:
        """
        No-op stub. Scoped dedup теперь реализуется через ScopedSourceDedupStore.
        Оставлен для совместимости с MatchProcessor Protocol до Stage 4.
        """


__all__ = ["MatchEngine"]
