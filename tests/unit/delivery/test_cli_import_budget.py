"""Import-budget guard: импорт CLI-дерева должен оставаться «тонким».

Построение Typer-дерева (и, как следствие, shell-completion / `--help`) обязано
импортировать только лёгкий граф. Бизнес-логика (DI, runtime, infra, polars,
config.models, command handlers) грузится лениво при реальном вызове команды.

Тест запускается в отдельном процессе, чтобы `sys.modules` не был загрязнён
другими тестами, уже импортировавшими тяжёлые модули.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_FORBIDDEN = (
    "dependency_injector",
    "polars",
    "fastapi",
    "httpx",
    "cryptography",
    "connector.delivery.cli.containers",
    "connector.delivery.cli.runtime",
    "connector.delivery.cli.context",
    "connector.config.loader",
    "connector.config.models",
    "connector.infra.target",
    "connector.infra.dictionaries",
    "connector.delivery.commands.mapping",
)


@pytest.mark.unit
def test_importing_cli_app_stays_thin() -> None:
    code = (
        "import sys\n"
        "import connector.delivery.cli.app  # noqa: F401\n"
        f"forbidden = {_FORBIDDEN!r}\n"
        "loaded = [m for m in forbidden if m in sys.modules]\n"
        "print(';'.join(loaded))\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Импорт connector.delivery.cli.app потянул тяжёлые модули "
        f"(нарушен import-budget): {result.stdout.strip()}.\n"
        "Перенеси импорт в тело команды/`main`/`_build_ctx` или в ленивый прокси."
    )
