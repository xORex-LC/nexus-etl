"""
Архитектурные guard-тесты для vault-слоя.

Цели:
1. Зафиксировать, что domain/usecases не зависят от concrete vault infra/delivery.
2. Оставить wiring concrete vault-адаптеров в composition root (`delivery/cli/bootstrap.py`).
3. Защитить resolve/planning/apply слои от прямых импортов concrete vault-реализаций.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
DOMAIN_ROOT = REPO_ROOT / "connector" / "domain"
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"

ALLOWED_INFRA_SECRETS_IMPORT_PATHS = {
    "connector/delivery/cli/bootstrap.py",
}
FLOW_LAYER_FILES = (
    REPO_ROOT / "connector" / "domain" / "transform" / "resolver" / "resolve_core.py",
    REPO_ROOT / "connector" / "domain" / "transform_dsl" / "compilers" / "resolve.py",
    REPO_ROOT / "connector" / "domain" / "planning" / "plan_builder.py",
    REPO_ROOT / "connector" / "usecases" / "import_apply_service.py",
)
FORBIDDEN_VAULT_CONCRETE_PREFIXES = (
    "connector.infra.secrets",
    "connector.domain.secrets.secret_vault",
    "connector.domain.secrets.vault_startup_guard",
    "connector.domain.secrets.vault_retention_service",
)


def _py_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if path.is_file()]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_domain_does_not_import_vault_infra_or_delivery() -> None:
    violations: list[str] = []
    for path in _py_files(DOMAIN_ROOT):
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith("connector.infra.secrets"):
                violations.append(f"{rel}: {module}")
            if module.startswith("connector.delivery"):
                violations.append(f"{rel}: {module}")
    assert violations == [], "Domain layer must not import vault infra/delivery:\n" + "\n".join(violations)


def test_usecases_do_not_import_vault_infra_or_delivery() -> None:
    violations: list[str] = []
    for path in _py_files(USECASES_ROOT):
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith("connector.infra.secrets"):
                violations.append(f"{rel}: {module}")
            if module.startswith("connector.delivery"):
                violations.append(f"{rel}: {module}")
    assert violations == [], "Use-cases must not import vault infra/delivery:\n" + "\n".join(violations)


def test_concrete_vault_wiring_is_only_in_bootstrap_outside_infra() -> None:
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        rel = _rel(path)
        if rel.startswith("connector/infra/"):
            continue
        for module in _imports(path):
            if module.startswith("connector.infra.secrets") and rel not in ALLOWED_INFRA_SECRETS_IMPORT_PATHS:
                violations.append(f"{rel}: {module}")
    assert violations == [], "Concrete vault infra imports must stay in bootstrap wiring:\n" + "\n".join(violations)


def test_resolve_planning_apply_layers_use_ports_not_concrete_vault_adapters() -> None:
    violations: list[str] = []
    for path in FLOW_LAYER_FILES:
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith(FORBIDDEN_VAULT_CONCRETE_PREFIXES):
                violations.append(f"{rel}: {module}")

    assert violations == [], (
        "resolve/planning/apply layers must depend on ports/contracts, not concrete vault adapters:\n"
        + "\n".join(violations)
    )


def test_import_apply_service_uses_retention_port_contract() -> None:
    service_path = REPO_ROOT / "connector" / "usecases" / "import_apply_service.py"
    imports = _imports(service_path)
    assert "connector.domain.ports.secrets.retention" in imports, (
        "ImportApplyService must depend on retention port contract"
    )


def test_cli_does_not_reintroduce_legacy_vault_flag() -> None:
    options_path = REPO_ROOT / "connector" / "delivery" / "cli" / "options.py"
    command_root = REPO_ROOT / "connector" / "delivery" / "commands"
    legacy_option = "--vault" + "-file"
    legacy_field = "vault" + "_file"
    legacy_const = "VAULT" + "_FILE"

    options_content = options_path.read_text(encoding="utf-8")
    assert legacy_option not in options_content
    assert legacy_const not in options_content

    for path in _py_files(command_root):
        content = path.read_text(encoding="utf-8")
        assert legacy_field not in content, f"legacy vault marker found in {_rel(path)}"
