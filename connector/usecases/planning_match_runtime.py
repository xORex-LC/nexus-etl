from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from connector.domain.ports.cache.identity import IdentityRepository
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.stages.stages import MatchStage
from connector.usecases.match_usecase import MatchUseCase


@dataclass(frozen=True)
class MatchRuntime:
    """
    Назначение:
        Собранный runtime для match-стадии (matcher + use-case + scope).
    """

    match_stage: MatchStage
    match_usecase: MatchUseCase
    runtime_scope: str
    identity_repo: IdentityRepository


@contextmanager
def open_match_runtime(
    *,
    run_id: str,
    match_stage: MatchStage,
    identity_repo: IdentityRepository,
    report_items_limit: int,
    include_matched_items: bool,
    batch_size: int,
    flush_interval_ms: int,
) -> Iterator[MatchRuntime]:
    """
    Назначение:
        Единая точка setup/cleanup для match-runtime.
    """
    runtime_scope = f"run:{run_id}"
    match_usecase = MatchUseCase(
        report_items_limit=report_items_limit,
        include_matched_items=include_matched_items,
        batch_size=batch_size,
        flush_interval_ms=flush_interval_ms,
    )
    runtime = MatchRuntime(
        match_stage=match_stage,
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
):
    """
    Назначение:
        Единый stream matched-результатов для downstream стадий.
    """
    return iter_ok(
        runtime.match_usecase.iter_matched(
            enriched_source=enriched_source,
            match_stage=runtime.match_stage,
            run_scope=runtime.runtime_scope,
        ),
        should_skip=lambda r: r.row is None,
    )
