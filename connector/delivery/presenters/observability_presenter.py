"""Observability CLI presenter — human-readable вывод для maintenance/obs команд.

Модуль форматирует результаты observability CLI-команд на delivery-границе:
ручной prune summary и содержимое найденных артефактов. Presenter не читает
ledger, не делает file I/O и не знает о DI wiring.

Границы ответственности:
    - Преобразовывать typed delivery results в строки для stdout.
    - Держать user-facing формат единообразным между `maintenance` и `obs`.

Вне ответственности:
    - Поиск артефактов и ретенция.
    - Запись отчётов, логов или pointers.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.common.observability import ObservabilityArtifactKind, ServiceComponent


@dataclass(frozen=True)
class PruneComponentSummary:
    """Итог manual-prune для одного компонента observability."""

    component: ServiceComponent
    deleted_logs: int
    deleted_reports: int
    deleted_plans: int
    touched_ledger: int


@dataclass(frozen=True)
class ArtifactDisplay:
    """User-facing представление найденного observability-артефакта."""

    component: ServiceComponent
    artifact_kind: ObservabilityArtifactKind
    path: str
    content: str
    tail_lines: int | None = None


class ObservabilityPresenter:
    """Форматировать stdout-вывод observability CLI-команд."""

    @staticmethod
    def render_prune(summaries: tuple[PruneComponentSummary, ...]) -> str:
        """Собрать текстовый summary ручного prune по компонентам."""
        if not summaries:
            return "No observability components were pruned."

        total_deleted = sum(
            item.deleted_logs + item.deleted_reports + item.deleted_plans
            for item in summaries
        )
        lines = [f"Pruned components={len(summaries)} deleted_files={total_deleted}"]
        for item in summaries:
            lines.append(
                (
                    f"{item.component.value}: logs={item.deleted_logs} "
                    f"reports={item.deleted_reports} plans={item.deleted_plans} "
                    f"ledger={item.touched_ledger}"
                )
            )
        return "\n".join(lines)

    @staticmethod
    def render_latest(display: ArtifactDisplay) -> str:
        """Собрать stdout-блок для `obs latest`."""
        return (
            f"[{display.component.value}:{display.artifact_kind.value}] {display.path}\n"
            f"{display.content}"
        )

    @staticmethod
    def render_tail(display: ArtifactDisplay) -> str:
        """Собрать stdout-блок для `obs tail`."""
        suffix = (
            f" last_lines={display.tail_lines}"
            if display.tail_lines is not None
            else ""
        )
        return (
            f"[{display.component.value}:{display.artifact_kind.value}] {display.path}{suffix}\n"
            f"{display.content}"
        )


__all__ = [
    "ArtifactDisplay",
    "ObservabilityPresenter",
    "PruneComponentSummary",
]
