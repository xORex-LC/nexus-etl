"""
Architecture guard tests for target boundaries.

Why these tests exist:
1. Delivery commands must not import low-level HTTP infra modules.
2. Delivery commands must not import Ankey-specific classes/exceptions directly.
3. Usecases/domain must not depend on connector.infra.target.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_ROOT = REPO_ROOT / "connector" / "delivery" / "commands"
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"
DOMAIN_ROOT = REPO_ROOT / "connector" / "domain"

FORBIDDEN_ANKEY_NAMES = {
    "AnkeyApiClient",
    "ApiError",
    "AnkeyRequestExecutor",
    "AnkeyTargetPagedReader",
}


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _import_froms(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            result.append((node.module or "", names))
    return result


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    bad: list[str] = []
    for path in _py_files(root):
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith(forbidden_prefixes):
                bad.append(f"{rel}: {module}")
    return bad


def test_delivery_commands_do_not_import_infra_http() -> None:
    violations = _violations(COMMANDS_ROOT, ("connector.infra.http",))
    assert violations == [], "Forbidden imports found:\n" + "\n".join(violations)


def test_delivery_commands_do_not_import_ankey_classes() -> None:
    violations: list[str] = []
    for path in _py_files(COMMANDS_ROOT):
        rel = _rel(path)
        for module, names in _import_froms(path):
            for name in names:
                if name in FORBIDDEN_ANKEY_NAMES:
                    violations.append(f"{rel}: from {module} import {name}")
    assert violations == [], "Forbidden Ankey imports found:\n" + "\n".join(violations)


def test_usecases_do_not_import_target_infra() -> None:
    violations = _violations(USECASES_ROOT, ("connector.infra.target",))
    assert violations == [], "Forbidden imports found:\n" + "\n".join(violations)


def test_domain_does_not_import_target_infra() -> None:
    violations = _violations(DOMAIN_ROOT, ("connector.infra.target",))
    assert violations == [], "Forbidden imports found:\n" + "\n".join(violations)
