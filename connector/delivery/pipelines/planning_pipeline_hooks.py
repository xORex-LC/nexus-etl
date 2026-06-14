"""Planning pipeline hooks — delivery-level wiring lifecycle callback-ов.

Модуль собирает `PipelineHooks` для planning/resolve pipeline. Он комбинирует
housekeeping callback-и с observability lifecycle callback-ами, не вмешиваясь в
логику match/resolve стадий.

Границы ответственности:
    - Собирать `PipelineHooks` с callback-ами housekeeping и observability.
    - Сохранять cleanup match/resolve scope на существующих lifecycle точках.

Вне ответственности:
    - Выполнение resolve/match логики.
    - Reporting use-case результатов.
"""

from __future__ import annotations

from connector.domain.transform.matcher.ports import IMatchScopeService
from connector.domain.transform.resolver.ports import IPendingExpiryService
from connector.domain.transform.stages.stages import PipelineHooks
from connector.common.observability import PipelineLifecycleEvents


class PlanningPipelineHooks:
    """
    Назначение:
        Фабрика hook-наборов для planning/resolve pipeline.

    Граница ответственности:
        - plan_hooks(): возвращает PipelineHooks для match+resolve прохода;
          на on_stage_complete("match") вызывает match_scope.clear_scope(),
          на on_stage_complete("resolve") вызывает pending_expiry.sweep().
        - Не занимается drain/report expired pending — это зона ResolveUseCase.
    """

    def __init__(
        self,
        pending_expiry: IPendingExpiryService,
        match_scope: IMatchScopeService,
        pipeline_lifecycle: PipelineLifecycleEvents | None = None,
    ) -> None:
        self._pending_expiry = pending_expiry
        self._match_scope = match_scope
        self._pipeline_lifecycle = pipeline_lifecycle

    def plan_hooks(self) -> PipelineHooks:
        def _on_stage_complete(
            stage_name: str, duration_ms: float, stats: dict | None
        ) -> None:
            if self._pipeline_lifecycle is not None:
                self._pipeline_lifecycle.stage_completed(
                    stage_name=stage_name,
                    duration_ns=_duration_ns_from_ms(duration_ms),
                    stats=stats,
                )
            if stage_name == "match":
                self._match_scope.clear_scope()
            elif stage_name == "resolve":
                self._pending_expiry.sweep()

        return PipelineHooks(
            on_stage_start=self._on_stage_start,
            on_stage_complete=_on_stage_complete,
            on_stage_error=self._on_stage_error,
            on_stage_abort=self._on_stage_abort,
        )

    def lifecycle_hooks(self) -> PipelineHooks:
        return PipelineHooks(
            on_stage_start=self._on_stage_start,
            on_stage_complete=self._on_lifecycle_stage_complete,
            on_stage_error=self._on_stage_error,
            on_stage_abort=self._on_stage_abort,
        )

    def _on_stage_start(self, stage_name: str) -> None:
        if self._pipeline_lifecycle is not None:
            self._pipeline_lifecycle.stage_started(stage_name=stage_name)

    def _on_lifecycle_stage_complete(
        self,
        stage_name: str,
        duration_ms: float,
        stats: dict | None,
    ) -> None:
        if self._pipeline_lifecycle is not None:
            self._pipeline_lifecycle.stage_completed(
                stage_name=stage_name,
                duration_ns=_duration_ns_from_ms(duration_ms),
                stats=stats,
            )

    def _on_stage_error(
        self, stage_name: str, exc: Exception, duration_ms: float
    ) -> None:
        if self._pipeline_lifecycle is not None:
            self._pipeline_lifecycle.stage_failed(
                stage_name=stage_name,
                exc=exc,
                duration_ns=_duration_ns_from_ms(duration_ms),
            )

    def _on_stage_abort(self, stage_name: str, duration_ms: float) -> None:
        if self._pipeline_lifecycle is not None:
            self._pipeline_lifecycle.stage_aborted(
                stage_name=stage_name,
                duration_ns=_duration_ns_from_ms(duration_ms),
            )


def _duration_ns_from_ms(duration_ms: float) -> int:
    return int(duration_ms * 1_000_000)


__all__ = ["PlanningPipelineHooks"]
