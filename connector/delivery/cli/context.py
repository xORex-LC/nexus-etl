"""CLI command context — типизированный runtime-контракт между delivery runtime и handlers.

Модуль описывает минимальный набор данных, который delivery runtime передаёт в обработчики
команд: logger, config snapshot, каталоги, контейнер и correlation ids. Здесь нет wiring,
handler-логики или I/O.

Responsibilities:
    - Дать единый typed context для unbound/bound состояний команды.
    - Сохранить границу между runtime orchestration и handler execution.

Out of scope:
    - Создание DI container и управление его lifecycle.
    - Выполнение бизнес-операций команд.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar
import logging

from connector.config.models import AppConfig
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
    app_config: AppConfig
    container: TContainer
    paths: CommandPaths | None = None
    extra: dict[str, Any] | None = None
    pipeline_run_id: str | None = None


UnboundCommandContext: TypeAlias = CommandContext[None]
BoundCommandContext: TypeAlias = CommandContext["AppContainer"]
