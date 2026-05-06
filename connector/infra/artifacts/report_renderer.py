"""
Назначение:
    Рендереры report артефактов для event-driven пути (DEC-001).

Граница ответственности:
    - Принимает готовый ReportEnvelope и сохраняет его в конкретный формат.
    - Не выполняет сборку envelope и не управляет runtime lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from connector.domain.reporting.context import asdict_envelope
from connector.domain.reporting.models import ReportEnvelope


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
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return report_path
