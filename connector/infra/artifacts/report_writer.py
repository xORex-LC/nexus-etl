from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from connector.domain.reporting.collector import ReportCollector, asdict_report

def createEmptyReport(runId: str, command: str, configSources: list[str]) -> ReportCollector:
    """
    Назначение:
        Создаёт пустой отчёт-скелет.

    Выходные данные:
        ReportCollector
    """
    collector = ReportCollector(run_id=runId, command=command)
    if configSources:
        collector.set_context("config", {"sources": configSources})
    return collector

def finalizeReport(report: ReportCollector, durationMs: int, logFile: str | None, cacheDir: str, reportDir: str) -> None:
    """
    Назначение:
        Финализирует отчёт: время завершения, длительность, пути.
    """
    report.set_context(
        "runtime",
        {
            "log_file": logFile,
            "cache_dir": cacheDir,
            "report_dir": reportDir,
        },
    )
    report.finish(duration_ms=durationMs)

def writeReportJson(report: ReportCollector, reportDir: str, fileBaseName: str) -> str:
    """
    Назначение:
        Записывает report.json на диск.

    Выходные данные:
        str
            Путь к файлу отчёта.
    """
    Path(reportDir).mkdir(parents=True, exist_ok=True)
    reportPath = str(Path(reportDir) / f"{fileBaseName}.json")

    data: dict[str, Any] = asdict_report(report.build())

    with open(reportPath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return reportPath
