"""
Назначение:
    Рендереры report артефактов для event-driven пути (DEC-001).

Граница ответственности:
    - Принимает готовый ReportEnvelope и сохраняет его в конкретный формат.
    - Не выполняет сборку envelope и не управляет runtime lifecycle.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from connector.common.observability import (
    ComponentIdentity,
    ObservabilityLayout,
    ServiceComponent,
)
from connector.domain.reporting.context import asdict_envelope
from connector.domain.reporting.models import ReportEnvelope
from connector.infra.artifacts._atomic_json import atomic_write_json


@runtime_checkable
class IReportRenderer(Protocol):
    """
    Назначение:
        Контракт рендеринга финального report envelope.
    """

    def render(
        self,
        *,
        envelope: ReportEnvelope,
        report_dir: str | Path,
        file_base_name: str,
    ) -> str: ...


class JsonReportRenderer(IReportRenderer):
    """
    Назначение:
        JSON-рендерер итогового отчёта.
    """

    def render(
        self,
        *,
        envelope: ReportEnvelope,
        report_dir: str | Path,
        file_base_name: str,
    ) -> str:
        report_dir_path = Path(report_dir)
        report_dir_path.mkdir(parents=True, exist_ok=True)
        report_path = str(report_dir_path / f"{file_base_name}.json")
        payload = asdict_envelope(envelope)
        atomic_write_json(path=report_path, payload=payload)
        return report_path

    def render_with_layout(
        self,
        *,
        envelope: ReportEnvelope,
        layout: ObservabilityLayout,
        component: ServiceComponent | ComponentIdentity,
        now: datetime | None = None,
    ) -> str:
        """Записать отчёт по новой component-aware observability раскладке.

        Args:
            envelope: Готовый report envelope.
            layout: Чистый observability layout resolver.
            component: Логический компонент сервиса.
            now: Время для детерминированного имени файла в тестах.

        Returns:
            Абсолютный путь к записанному report artifact.
        """
        report_path = layout.report_file(component, now=now)
        payload = asdict_envelope(envelope)
        atomic_write_json(path=report_path, payload=payload)
        return str(report_path)
