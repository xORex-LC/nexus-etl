from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar
import logging

from connector.config.app_settings import AppSettings
from connector.domain.diagnostics.catalog import ErrorCatalog

if TYPE_CHECKING:
    from connector.delivery.cli.containers import AppContainer

TContainer = TypeVar("TContainer")


@dataclass(frozen=True)
class CommandPaths:
    """
    Назначение:
        Локальные пути выполнения команды (например, куда складывать отчёты).
    """

    report_dir: str | None = None
    work_dir: str | None = None


@dataclass(frozen=True)
class CommandContext(Generic[TContainer]):
    """
    Назначение:
        Унифицированный контекст выполнения CLI-команды.

    Контракт:
        Generic-параметр `TContainer` фиксирует состояние контекста:
        - `CommandContext[None]`: unbound-контекст до composition root wiring.
        - `CommandContext[AppContainer]`: bound-контекст после wiring в runtime.
    """

    logger: logging.Logger
    run_id: str
    catalog: ErrorCatalog
    strict: bool
    app_settings: AppSettings
    container: TContainer
    paths: CommandPaths | None = None
    extra: dict[str, Any] | None = None


UnboundCommandContext: TypeAlias = CommandContext[None]
BoundCommandContext: TypeAlias = CommandContext["AppContainer"]
