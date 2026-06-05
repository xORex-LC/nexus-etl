"""Observability artifact commands — `nexus obs latest` и `nexus obs tail`.

Модуль реализует delivery-handlers для чтения последних observability-артефактов
через ledger-backed viewer. Команды не знают о layout, symlink/copy fallback или
backend-деталях ledger: эти обязанности остаются в infra.

Границы ответственности:
    - Разрешить последний артефакт компонента через observability viewer.
    - Прочитать полный текст или хвост строк и напечатать его через presenter.

Вне ответственности:
    - Запись ledger и публикация latest pointers.
    - Retention и любые business/usecase операции.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.common.observability import (
    ObservabilityArtifactKind,
    ServiceComponent,
)
from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import result_with
from connector.delivery.presenters.observability_presenter import (
    ArtifactDisplay,
    ObservabilityPresenter,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import log_event


@dataclass(frozen=True)
class LatestOptions:
    component: ServiceComponent
    artifact: ObservabilityArtifactKind = ObservabilityArtifactKind.REPORT


@dataclass(frozen=True)
class TailOptions:
    component: ServiceComponent
    artifact: ObservabilityArtifactKind = ObservabilityArtifactKind.LOG
    lines: int = 20


def latest_handler(
    ctx: BoundCommandContext,
    opts: LatestOptions,
    report_sink,
) -> CommandResult:
    """Показать содержимое последнего артефакта выбранного компонента."""
    _ = report_sink
    run_id = ctx.run_id
    viewer = ctx.container.observability.artifact_viewer()

    try:
        artifact_path = viewer.resolve_latest_artifact_path(
            component=opts.component,
            artifact_kind=opts.artifact,
        )
        if artifact_path is None:
            typer.echo(
                (
                    "ERROR: latest {artifact} artifact for component '{component}' "
                    "was not found"
                ).format(
                    artifact=opts.artifact.value,
                    component=opts.component.value,
                ),
                err=True,
            )
            return result_with(SystemErrorCode.IO_ERROR)

        content = viewer.read_text(path=artifact_path)
        typer.echo(
            ObservabilityPresenter.render_latest(
                ArtifactDisplay(
                    component=opts.component,
                    artifact_kind=opts.artifact,
                    path=str(artifact_path),
                    content=content,
                )
            )
        )
        log_event(
            ctx.logger,
            logging.INFO,
            run_id,
            "observability",
            f"Displayed latest {opts.artifact.value}: {artifact_path}",
        )
        return result_with(SystemErrorCode.OK)
    except Exception as exc:
        log_event(
            ctx.logger,
            logging.ERROR,
            run_id,
            "observability",
            f"obs latest failed: {exc}",
        )
        typer.echo("ERROR: obs latest failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)


def tail_handler(
    ctx: BoundCommandContext,
    opts: TailOptions,
    report_sink,
) -> CommandResult:
    """Показать хвост последнего артефакта выбранного компонента."""
    _ = report_sink
    run_id = ctx.run_id
    viewer = ctx.container.observability.artifact_viewer()

    try:
        artifact_path = viewer.resolve_latest_artifact_path(
            component=opts.component,
            artifact_kind=opts.artifact,
        )
        if artifact_path is None:
            typer.echo(
                (
                    "ERROR: latest {artifact} artifact for component '{component}' "
                    "was not found"
                ).format(
                    artifact=opts.artifact.value,
                    component=opts.component.value,
                ),
                err=True,
            )
            return result_with(SystemErrorCode.IO_ERROR)

        content = viewer.tail_text(path=artifact_path, lines=opts.lines)
        typer.echo(
            ObservabilityPresenter.render_tail(
                ArtifactDisplay(
                    component=opts.component,
                    artifact_kind=opts.artifact,
                    path=str(artifact_path),
                    content=content,
                    tail_lines=opts.lines,
                )
            )
        )
        log_event(
            ctx.logger,
            logging.INFO,
            run_id,
            "observability",
            f"Displayed tail for {opts.artifact.value}: {artifact_path}",
        )
        return result_with(SystemErrorCode.OK)
    except Exception as exc:
        log_event(
            ctx.logger,
            logging.ERROR,
            run_id,
            "observability",
            f"obs tail failed: {exc}",
        )
        typer.echo("ERROR: obs tail failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)


__all__ = ["LatestOptions", "TailOptions", "latest_handler", "tail_handler"]
