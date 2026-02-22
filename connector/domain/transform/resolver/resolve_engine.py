"""
Назначение:
    StageEngine-обвязка resolver: ResolveSpec -> ResolveDsl -> ResolveCore.

Граница ответственности:
    - Owns: компиляция ResolveSpec → ResolveCore.
    - Does NOT: бизнес-логика resolve (делегирует ResolveCore).

    Поддерживает два пути инициализации (DEC-004 transition):
    - ctx: StageExecutionContext — новый путь (capabilities из context).
    - scattered params (cache_gateway, settings, catalog) — legacy путь.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.roles import ResolveRuntimePort
from connector.domain.transform_dsl.build_options import ResolveDslBuildOptions
from connector.domain.transform_dsl.specs import ResolveSpec, SinkSpec
from connector.domain.transform.resolver.resolve_core import ResolveCore
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.transform_dsl.compilers.resolve import ResolveDsl

if TYPE_CHECKING:
    from connector.domain.transform.context import StageExecutionContext


class ResolveEngine:
    """
    Назначение/ответственность:
        Тонкая runtime-обвязка resolve-стадии без бизнес-логики resolver.

    Поддерживает два пути инициализации (DEC-004 transition):
        - ctx: StageExecutionContext — scoped capabilities (новый путь).
        - cache_gateway/settings/catalog — scattered params (legacy путь).
    """

    def __init__(
        self,
        *,
        spec: ResolveSpec,
        ctx: StageExecutionContext | None = None,
        cache_gateway: ResolveRuntimePort | None = None,
        settings: ResolverSettings | None = None,
        catalog: ErrorCatalog | None = None,
        sink_spec: SinkSpec | None = None,
        dsl: ResolveDsl | None = None,
        options: ResolveDslBuildOptions | None = None,
    ) -> None:
        if ctx is not None:
            resolved_gateway = ctx.get(ResolveRuntimePort)
            resolved_settings = ctx.get(ResolverSettings)
            resolved_catalog = ctx.metadata.catalog
            resolved_sink_spec = sink_spec or ctx.metadata.sink_spec
        else:
            resolved_gateway = cache_gateway
            resolved_settings = settings
            resolved_catalog = catalog or ErrorCatalog(dataset="", items={})
            resolved_sink_spec = sink_spec

        self.dsl = dsl or ResolveDsl(options=options)
        compiled = self.dsl.compile(spec, sink_spec=resolved_sink_spec)
        self.resolve_rules = compiled.resolve_rules
        self.link_rules = compiled.link_rules
        self.core = ResolveCore(
            self.resolve_rules,
            self.link_rules,
            cache_gateway=resolved_gateway,
            settings=resolved_settings,
            catalog=resolved_catalog,
            sink_spec=resolved_sink_spec,
        )

    @property
    def settings(self) -> ResolverSettings | None:
        return self.core.settings

    @property
    def cache_gateway(self):
        return self.core.cache_gateway

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
