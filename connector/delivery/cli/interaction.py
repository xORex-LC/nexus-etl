"""CLI interaction helpers — единая точка интерактивных prompt-вызовов

Модуль содержит delivery-специфичные обёртки над `typer.confirm()` и
`typer.prompt()`. Обёртки синхронизируются с `InteractiveIoGate`, чтобы во
время prompt-а observability console/capture mirror временно замолкал и не
портил терминальный UX.

Responsibilities:
    - Выполнять prompt/confirm через Typer в интерактивном gate-режиме.
    - Скрывать детали временного suppress-режима от command handlers.
    - Давать единый API для user-facing интерактивных сценариев CLI.

Out of scope:
    - Валидация бизнес-смысла введённого значения.
    - Реализация `getpass`-prompt для infra-слоя.
"""

from __future__ import annotations

import typer

from connector.common.interactive_io import InteractiveIoGate


def confirm_with_gate(
    text: str,
    *,
    gate: InteractiveIoGate,
    default: bool = False,
    err: bool = False,
) -> bool:
    """Запросить подтверждение, временно подавив console/capture mirror."""
    with gate.suppress_observability_mirror():
        return bool(typer.confirm(text, default=default, err=err))


def prompt_secret_with_gate(
    text: str,
    *,
    gate: InteractiveIoGate,
    confirmation_prompt: bool = False,
) -> str:
    """Запросить скрытый ввод через Typer, временно подавив mirror."""
    with gate.suppress_observability_mirror():
        return str(
            typer.prompt(
                text,
                hide_input=True,
                confirmation_prompt=confirmation_prompt,
            )
        )


__all__ = [
    "confirm_with_gate",
    "prompt_secret_with_gate",
]
