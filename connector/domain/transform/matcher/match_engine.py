"""
Назначение:
    StageEngine-обвязка matcher: MatchSpec -> MatchDsl -> MatchCore.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform_dsl.build_options import MatchDslBuildOptions
from connector.domain.transform_dsl.specs import MatchSpec
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform_dsl.compilers.match import MatchDsl
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform_dsl.compilers.resolve import ResolveRules


class MatchEngine:
    """
    Назначение/ответственность:
        Тонкая runtime-обвязка match-стадии без бизнес-логики матчинга.
    """

    def __init__(
        self,
        *,
        spec: MatchSpec,
        dataset: str,
        cache_gateway: MatchRuntimePort,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        catalog: ErrorCatalog,
        dsl: MatchDsl | None = None,
        options: MatchDslBuildOptions | None = None,
    ) -> None:
        self.dsl = dsl or MatchDsl(options=options)
        self.matching_rules = self.dsl.compile(spec)
        self.core = MatchCore(
            dataset=dataset,
            cache_gateway=cache_gateway,
            matching_rules=self.matching_rules,
            resolve_rules=resolve_rules,
            include_deleted=include_deleted,
            catalog=catalog,
        )

    def match(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        return self.core.match(enriched)

    def match_with_source_dedup(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        return self.core.match_with_source_dedup(enriched)

    def match_stream(self, enriched_source):
        return self.core.match_stream(enriched_source)

    def reset_source_dedup(self) -> None:
        self.core.reset_source_dedup()

    def bind_runtime_scope(self, scope: str | None) -> None:
        self.core.bind_runtime_scope(scope)


__all__ = ["MatchEngine"]
