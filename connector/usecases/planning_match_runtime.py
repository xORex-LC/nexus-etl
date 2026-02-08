from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from connector.datasets.spec import PlanningBundle
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.identity import IdentityRepository
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.matching.match_engine import MatchEngine
from connector.domain.transform.matching.resolve_deps import PlanningDependencies
from connector.usecases.match_usecase import MatchUseCase


@dataclass(frozen=True)
class MatchRuntime:
    """
    Назначение:
        Собранный runtime для match-стадии (matcher + use-case + scope).
    """

    matcher: MatchEngine
    match_usecase: MatchUseCase
    runtime_scope: str
    identity_repo: IdentityRepository


def _require_match_deps(deps: PlanningDependencies) -> tuple[Any, IdentityRepository]:
    cache_repo = deps.cache_repo
    if cache_repo is None:
        raise ValueError("planning cache_repo is not configured")
    identity_repo = deps.identity_repo
    if identity_repo is None:
        raise ValueError("planning identity_repo is not configured")
    return cache_repo, identity_repo


@contextmanager
def open_match_runtime(
    *,
    dataset: str,
    include_deleted: bool,
    run_id: str,
    planning_deps: PlanningDependencies,
    planning_bundle: PlanningBundle,
    catalog: ErrorCatalog,
    report_items_limit: int,
    include_matched_items: bool,
    batch_size: int,
    flush_interval_ms: int,
) -> Iterator[MatchRuntime]:
    """
    Назначение:
        Единая точка setup/cleanup для match-runtime.
    """
    cache_repo, identity_repo = _require_match_deps(planning_deps)
    runtime_scope = f"run:{run_id}"
    matcher = MatchEngine(
        spec=planning_bundle.match_spec,
        dataset=dataset,
        cache_repo=cache_repo,
        resolve_rules=planning_bundle.resolve_rules,
        include_deleted=include_deleted,
        catalog=catalog,
        identity_repo=identity_repo,
    )
    match_usecase = MatchUseCase(
        report_items_limit=report_items_limit,
        include_matched_items=include_matched_items,
        batch_size=batch_size,
        flush_interval_ms=flush_interval_ms,
    )
    runtime = MatchRuntime(
        matcher=matcher,
        match_usecase=match_usecase,
        runtime_scope=runtime_scope,
        identity_repo=identity_repo,
    )
    try:
        yield runtime
    finally:
        identity_repo.clear_runtime_scope(runtime_scope)


def iter_matched_ok(
    *,
    runtime: MatchRuntime,
    enriched_source: Iterable[TransformResult[Any]],
    catalog: ErrorCatalog,
):
    """
    Назначение:
        Единый stream matched-результатов для downstream стадий.
    """
    return iter_ok(
        runtime.match_usecase.iter_matched(
            enriched_source=enriched_source,
            matcher=runtime.matcher,
            catalog=catalog,
            run_scope=runtime.runtime_scope,
        ),
        should_skip=lambda r: r.row is None,
    )
