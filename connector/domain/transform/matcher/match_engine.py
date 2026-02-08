"""
Назначение:
    StageEngine-обвязка matcher: MatchSpec -> MatchDsl -> MatchCore.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.identity import IdentityRepository
from connector.domain.ports.cache.repository import CacheRepositoryProtocol
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.dsl.specs import MatchSpec
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform.matcher.match_dsl import MatchDsl
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform.matcher.rules import ResolveRules


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
        cache_repo: CacheRepositoryProtocol,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        catalog: ErrorCatalog,
        identity_repo: IdentityRepository | None = None,
        dsl: MatchDsl | None = None,
    ) -> None:
        self.dsl = dsl or MatchDsl()
        self.matching_rules = self.dsl.compile(spec)
        self.core = MatchCore(
            dataset=dataset,
            cache_repo=cache_repo,
            matching_rules=self.matching_rules,
            resolve_rules=resolve_rules,
            include_deleted=include_deleted,
            catalog=catalog,
            identity_repo=identity_repo,
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
