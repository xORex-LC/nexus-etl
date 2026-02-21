"""
Архитектурные guard-тесты для границ DI в delivery.

Зачем нужны:
1. Lifecycle AppContainer должен жить только в runtime composition root.
2. Запрещаем ручные вызовы shutdown_resources() внутри command handlers.
3. Проверяем, что handlers используют контракт bound-контекста.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_ROOT = REPO_ROOT / "connector" / "delivery" / "commands"

IGNORED_COMMAND_MODULES = {
    "__init__.py",
    "common.py",
    "import_apply_dry_run_executor.py",
}


def _py_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if path.is_file()]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _call_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "AppContainer":
                violations.append(f"{_rel(path)} создаёт AppContainer()")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "shutdown_resources":
                violations.append(f"{_rel(path)} вызывает shutdown_resources()")
    return violations


def _has_bound_context_import(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "connector.delivery.cli.context":
            for alias in node.names:
                if alias.name == "BoundCommandContext":
                    return True
    return False


def test_delivery_commands_do_not_manage_app_container_lifecycle() -> None:
    violations: list[str] = []
    for path in _py_files(COMMANDS_ROOT):
        if path.name in IGNORED_COMMAND_MODULES:
            continue
        violations.extend(_call_violations(path))
    assert violations == [], "Command handlers не должны управлять lifecycle AppContainer:\n" + "\n".join(violations)


def test_delivery_command_modules_use_bound_context_contract() -> None:
    violations: list[str] = []
    for path in _py_files(COMMANDS_ROOT):
        if path.name in IGNORED_COMMAND_MODULES:
            continue
        content = path.read_text(encoding="utf-8")
        if "def handler(" not in content:
            continue
        if not _has_bound_context_import(path):
            violations.append(f"{_rel(path)} не импортирует BoundCommandContext")
    assert violations == [], "Handlers должны типизировать ctx как BoundCommandContext:\n" + "\n".join(violations)
