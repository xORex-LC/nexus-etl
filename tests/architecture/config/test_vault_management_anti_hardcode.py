from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONNECTOR_ROOT = ROOT / "connector"

ALLOWED_VM_SETTINGS_CONSTRUCTORS = {
    "connector/config/projections.py",
}

ALLOWED_DEFAULT_ENV_LITERAL_FILES = {
    "connector/config/models.py",
}

VAULT_MANAGEMENT_DEFAULT_ENV_LITERALS = {
    "ANKEY_VAULT_ADMIN_PASSWORD_HASH",
    "ANKEY_VAULT_ADMIN_PASSWORD",
}


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _iter_string_literals(path: Path) -> list[str]:
    tree = _parse(path)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


def test_vault_management_settings_constructed_only_in_config_projection() -> None:
    violations: list[str] = []
    for path in _python_files(CONNECTOR_ROOT):
        rel = _rel(path)
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) != "VaultManagementSettings":
                continue
            if rel not in ALLOWED_VM_SETTINGS_CONSTRUCTORS:
                violations.append(rel)
                break

    assert violations == [], (
        "VaultManagementSettings must be constructed only in config projection layer:\n"
        + "\n".join(sorted(violations))
    )


def test_vault_management_default_env_var_literals_live_only_in_config_layer() -> None:
    violations: list[str] = []
    for path in _python_files(CONNECTOR_ROOT):
        rel = _rel(path)
        if rel in ALLOWED_DEFAULT_ENV_LITERAL_FILES:
            continue
        literals = set(_iter_string_literals(path))
        leaked = sorted(VAULT_MANAGEMENT_DEFAULT_ENV_LITERALS.intersection(literals))
        if leaked:
            violations.append(f"{rel}: {', '.join(leaked)}")

    assert violations == [], (
        "Vault-management default ENV literals must be declared only in config models:\n"
        + "\n".join(violations)
    )

