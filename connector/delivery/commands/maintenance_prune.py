"""Manual observability retention command — `nexus maintenance prune`.

Модуль реализует delivery-handler для ручного запуска observability sweeper по
активному config. Команда не содержит бизнес-логики: она лишь оркестрирует
infra-retention adapter и форматирует summary через presenter.

Границы ответственности:
    - Вызвать safe retention sweep по выбранным компонентам.
    - Напечатать user-facing summary на stdout.

Вне ответственности:
    - Реализация самой ретенции.
    - Ledger query/read и чтение артефактов.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.common.observability import ServiceComponent
from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import result_with
from connector.delivery.presenters.observability_presenter import (
    ObservabilityPresenter,
    PruneComponentSummary,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import log_event


@dataclass(frozen=True)
class Options:
    component: ServiceComponent | None = None
    force: bool = False


def handler(ctx: BoundCommandContext, opts: Options, report_sink) -> CommandResult:
    """Запустить manual prune observability-артефактов по config."""
    _ = report_sink
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App config is not initialized")

    run_id = ctx.run_id
    sweeper = ctx.container.observability.sweeper()
    components = (
        (opts.component,) if opts.component is not None else tuple(ServiceComponent)
    )
    summaries: list[PruneComponentSummary] = []

    try:
        for component in components:
            log_result = None
            report_result = None
            plan_result = None
            ledger_result = None

            if app_config.observability.logging.sinks.file.enabled:
                log_result = sweeper.sweep_logs(
                    component=component,
                    retention_days=app_config.observability.logging.sinks.file.retention_days,
                    retention_backups=app_config.observability.logging.sinks.file.retention_backups,
                    ignore_marker=opts.force,
                )
            report_result = sweeper.sweep_reports(
                component=component,
                retention_days=app_config.observability.reporting.retention_days,
                ignore_marker=opts.force,
            )
            plan_result = sweeper.sweep_plans(
                component=component,
                retention_days=app_config.observability.plans.retention_days,
                ignore_marker=opts.force,
            )
            if app_config.observability.ledger.enabled:
                ledger_result = sweeper.sweep_ledger(
                    component=component,
                    retention_days=app_config.observability.logging.sinks.file.retention_days,
                    ignore_marker=opts.force,
                )

            summaries.append(
                PruneComponentSummary(
                    component=component,
                    deleted_logs=len(log_result.deleted_files) if log_result else 0,
                    deleted_reports=len(report_result.deleted_files)
                    if report_result
                    else 0,
                    deleted_plans=len(plan_result.deleted_files) if plan_result else 0,
                    touched_ledger=len(ledger_result.deleted_files)
                    if ledger_result
                    else 0,
                )
            )

        typer.echo(ObservabilityPresenter.render_prune(tuple(summaries)))
        log_event(
            ctx.logger,
            logging.INFO,
            run_id,
            "observability",
            f"Manual prune completed for components={len(summaries)}",
        )
        return result_with(SystemErrorCode.OK)
    except Exception as exc:
        log_event(
            ctx.logger,
            logging.ERROR,
            run_id,
            "observability",
            f"Manual prune failed: {exc}",
        )
        typer.echo("ERROR: maintenance prune failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)


__all__ = ["Options", "handler"]
