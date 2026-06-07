"""CLI package — ленивые re-export'ы.

Re-export'ы (`CommandContext`, `Requirements`, `options`, …) отдаются лениво через
PEP 562 `__getattr__`, чтобы импорт любого подмодуля пакета (например `app` для
shell-completion или `completions` для `autocompletion=`) НЕ тянул `context` →
`config.models` и весь domain/config-граф. Тяжёлый импорт случается только при
фактическом обращении к атрибуту.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__all__ = [
    "CommandContext",
    "UnboundCommandContext",
    "BoundCommandContext",
    "CommandPaths",
    "Requirements",
    "options",
]

if TYPE_CHECKING:
    from connector.delivery.cli import options
    from connector.delivery.cli.context import (
        BoundCommandContext,
        CommandContext,
        CommandPaths,
        UnboundCommandContext,
    )
    from connector.delivery.cli.requirements import Requirements

_CONTEXT_EXPORTS = {
    "CommandContext",
    "UnboundCommandContext",
    "BoundCommandContext",
    "CommandPaths",
}


def __getattr__(name: str) -> Any:
    # Только class-реэкспорты идут через ленивый __getattr__. Подмодули
    # (`options`, `context`, `requirements`) импортируются штатным submodule-import
    # без участия __getattr__, поэтому здесь их трогать нельзя (иначе рекурсия).
    if name in _CONTEXT_EXPORTS:
        context = importlib.import_module("connector.delivery.cli.context")
        return getattr(context, name)
    if name == "Requirements":
        requirements = importlib.import_module("connector.delivery.cli.requirements")
        return requirements.Requirements
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
