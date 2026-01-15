from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from .timeUtils import getNowIso

@dataclass
class ReportMeta:
    """
    Назначение:
        Метаданные отчёта запуска команды.
    """
    run_id: str
    command: str
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = None

    csv_path: str | None = None
    csv_rows_total: int | None = None
    csv_rows_processed: int | None = None

    log_file: str | None = None
    cache_dir: str | None = None
    report_dir: str | None = None
    api_base_url: str | None = None
    pages_users: int | None = None
    pages_orgs: int | None = None
    mode: str | None = None
    page_size: int | None = None
    max_pages: int | None = None
    timeout_seconds: float | None = None
    retries: int | None = None
    include_deleted_users: bool | None = None
    skipped_deleted_users: int | None = None
    on_missing_org: str | None = None
    plan_file: str | None = None
    plan_path: str | None = None
    stop_on_first_error: bool | None = None
    max_actions: int | None = None
    dry_run: bool | None = None

    config_sources: list[str] = field(default_factory=list)

@dataclass
class ReportSummary:
    """
    Назначение:
        Сводные счётчики. На этапе 2 — заполняются нулями.
    """
    planned_create: int = 0
    planned_update: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: int = 0

@dataclass
class Report:
    """
    Назначение:
        Корневой объект отчёта.
    """
    meta: ReportMeta
    summary: ReportSummary
    items: list[dict] = field(default_factory=list)

def createEmptyReport(runId: str, command: str, configSources: list[str]) -> Report:
    """
    Назначение:
        Создаёт пустой отчёт-скелет.

    Выходные данные:
        Report
    """
    meta = ReportMeta(
        run_id=runId,
        command=command,
        started_at=getNowIso(),
        config_sources=configSources or [],
    )
    return Report(meta=meta, summary=ReportSummary(), items=[])

def finalizeReport(report: Report, durationMs: int, logFile: str | None, cacheDir: str, reportDir: str) -> None:
    """
    Назначение:
        Финализирует отчёт: время завершения, длительность, пути.
    """
    report.meta.finished_at = getNowIso()
    report.meta.duration_ms = durationMs
    report.meta.log_file = logFile
    report.meta.cache_dir = cacheDir
    report.meta.report_dir = reportDir

def writeReportJson(report: Report, reportDir: str, fileBaseName: str) -> str:
    """
    Назначение:
        Записывает report.json на диск.

    Выходные данные:
        str
            Путь к файлу отчёта.
    """
    Path(reportDir).mkdir(parents=True, exist_ok=True)
    reportPath = str(Path(reportDir) / f"{fileBaseName}.json")

    data: dict[str, Any] = {
        "meta": asdict(report.meta),
        "summary": asdict(report.summary),
        "items": report.items,
    }

    with open(reportPath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return reportPath
