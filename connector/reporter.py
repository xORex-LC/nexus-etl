from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .timeUtils import getNowIso


@dataclass
class ReportMeta:
    """
    Назначение:
        Метаданные отчёта запуска команды.

    Поля:
        run_id: str
        command: str
        started_at: str
        finished_at: str | None
        duration_ms: int | None
        csv_path: str | None
        csv_rows_total: int | None
        csv_rows_processed: int | None
        log_file: str | None
        cache_dir: str | None
        report_dir: str | None
        config_sources: list[str]
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
    config_sources: list[str] = None


@dataclass
class ReportSummary:
    """
    Назначение:
        Сводные счётчики. На этапе 2 — заполняются нулями.

    Поля:
        planned_create, planned_update, created, updated, skipped, failed, warnings: int
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

    Поля:
        meta: ReportMeta
        summary: ReportSummary
        items: list[dict]
            На этапе 2 — пустой список.
    """
    meta: ReportMeta
    summary: ReportSummary
    items: list[dict]


def createEmptyReport(runId: str, command: str, configSources: list[str]) -> Report:
    """
    Назначение:
        Создаёт пустой отчёт-скелет для команды.

    Входные данные:
        runId: str
        command: str
        configSources: list[str]

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

    Входные данные:
        report: Report
        durationMs: int
        logFile: str | None
        cacheDir: str
        reportDir: str

    Выходные данные:
        None
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

    Входные данные:
        report: Report
        reportDir: str
        fileBaseName: str
            Например: "report_import_<runId>"

    Выходные данные:
        str
            Полный путь к созданному файлу.

    Алгоритм:
        - Создать reportDir
        - json dump с ensure_ascii=False
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