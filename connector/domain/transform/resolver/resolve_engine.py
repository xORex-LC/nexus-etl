"""
Назначение:
    StageEngine-обвязка resolver: ResolveSpec -> ResolveDsl -> ResolveCore.
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.gateway import CacheGatewayPort
from connector.domain.dsl.build_options import ResolveDslBuildOptions
from connector.domain.dsl.specs import ResolveSpec, SinkSpec
from connector.domain.transform.resolver.resolve_core import ResolveCore
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.transform.resolver.resolve_dsl import ResolveDsl


class ResolveEngine:
    """
    Назначение/ответственность:
        Тонкая runtime-обвязка resolve-стадии без бизнес-логики resolver.
    """

    def __init__(
        self,
        *,
        spec: ResolveSpec,
        identity_repo: CacheGatewayPort | None,
        pending_repo: CacheGatewayPort | None,
        settings: ResolverSettings | None,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
        dsl: ResolveDsl | None = None,
        options: ResolveDslBuildOptions | None = None,
    ) -> None:
        self.dsl = dsl or ResolveDsl(options=options)
        compiled = self.dsl.compile(spec, sink_spec=sink_spec)
        self.resolve_rules = compiled.resolve_rules
        self.link_rules = compiled.link_rules
        self.core = ResolveCore(
            self.resolve_rules,
            self.link_rules,
            identity_repo=identity_repo,
            pending_repo=pending_repo,
            settings=settings,
            catalog=catalog,
            sink_spec=sink_spec,
        )

    @property
    def settings(self) -> ResolverSettings | None:
        return self.core.settings

    @property
    def pending_repo(self):
        return self.core.pending_repo

    def drain_expired(self):
        return self.core.drain_expired()

    def build_batch_index(self, matched_rows: list, dataset: str) -> dict[str, dict[str, list[str]]]:
        return self.core.build_batch_index(matched_rows, dataset)

    def resolve(
        self,
        matched: MatchedRow,
        *,
        target_id_map: dict[str, str],
        meta: dict[str, Any] | None = None,
        batch_index: dict[str, dict[str, list[str]]] | None = None,
    ):
        return self.core.resolve(
            matched,
            target_id_map=target_id_map,
            meta=meta,
            batch_index=batch_index,
        )


__all__ = ["ResolveEngine"]
