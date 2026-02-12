from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

from connector.config.app_settings import AppSettings
from connector.domain.diagnostics.catalog import ErrorCatalog


@dataclass(frozen=True)
class CommandPaths:
    """
    Назначение:
        Локальные пути выполнения команды (например, куда складывать отчёты).
    """

    report_dir: str | None = None
    work_dir: str | None = None


@dataclass(frozen=True)
class CommandContext:
    """
    Назначение:
        Унифицированный контекст выполнения CLI-команды.
    """

    logger: logging.Logger
    run_id: str
    catalog: ErrorCatalog
    strict: bool
    app_settings: AppSettings
    paths: CommandPaths | None = None
    extra: dict[str, Any] | None = None
