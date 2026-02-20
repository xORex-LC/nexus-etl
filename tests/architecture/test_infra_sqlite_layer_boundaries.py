"""
Архитектурные guard-тесты для unified SQLite infra layer (CACHE-DEC-002 Block 3).

Цели:
1. Domain не импортирует connector.infra.sqlite.
2. sqlite3.connect() вызывается только в connector/infra/sqlite/engine.py.
3. Identity-репозитории находятся в правильном пакете (identity/sqlite/, не cache/repository/).
4. bootstrap.py отсутствует (не реинтродуцирован).
5. VaultSqliteDb и openVaultDb отсутствуют в repo.
6. openCacheDb отсутствует в repo.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
DOMAIN_ROOT = REPO_ROOT / "connector" / "domain"
TESTS_ROOT = REPO_ROOT / "tests"

_NEW_SQLITE_ENGINE = "connector/infra/sqlite/engine.py"


def _py_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if path.is_file()]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def test_domain_does_not_import_infra_sqlite() -> None:
    """
    connector/domain/** никогда не импортирует connector.infra.sqlite.

    Гарантирует, что domain-слой не знает о конкретной SQLite-инфраструктуре.
    """
    violations: list[str] = []
    for path in _py_files(DOMAIN_ROOT):
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith("connector.infra.sqlite"):
                violations.append(f"{rel}: {module}")
    assert violations == [], (
        "Domain layer must not import connector.infra.sqlite:\n" + "\n".join(violations)
    )


def test_sqlite_connection_does_not_leak() -> None:
    """
    sqlite3.connect() вызывается только в connector/infra/sqlite/engine.py.

    Гарантирует, что все SQLite-соединения создаются через open_sqlite()
    и не просачиваются наружу через прямые вызовы sqlite3.connect().
    """
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        rel = _rel(path)
        if rel == _NEW_SQLITE_ENGINE:
            continue
        content = path.read_text(encoding="utf-8")
        if "sqlite3.connect(" in content:
            violations.append(rel)
    assert violations == [], (
        "sqlite3.connect() must only be called in connector/infra/sqlite/engine.py.\n"
        "Other files must use open_sqlite():\n" + "\n".join(violations)
    )


def test_identity_repos_are_in_correct_package() -> None:
    """
    connector/infra/cache/repository/ не содержит *identity* или *pending_links* файлов.

    Гарантирует, что identity-репозитории перенесены в connector/infra/identity/sqlite/.
    """
    cache_repo_dir = CONNECTOR_ROOT / "infra" / "cache" / "repository"
    forbidden_patterns = ("identity", "pending_links", "pending")
    violations: list[str] = []
    for path in cache_repo_dir.glob("*.py"):
        name = path.stem.lower()
        for pattern in forbidden_patterns:
            if pattern in name:
                violations.append(str(path.relative_to(REPO_ROOT)))
                break
    assert violations == [], (
        "Identity/pending repos must be in connector/infra/identity/sqlite/, not cache/repository/:\n"
        + "\n".join(violations)
    )


def test_bootstrap_is_removed() -> None:
    """
    connector/delivery/cli/bootstrap.py отсутствует в репозитории.

    Гарантирует, что legacy composition root не реинтродуцирован.
    Новый composition root: connector/delivery/cli/containers.py
    """
    bootstrap_path = CONNECTOR_ROOT / "delivery" / "cli" / "bootstrap.py"
    assert not bootstrap_path.exists(), (
        "bootstrap.py must be removed; use containers.py as composition root"
    )


def test_vault_sqlite_db_class_is_removed() -> None:
    """
    VaultSqliteDb и openVaultDb отсутствуют в репозитории.

    Гарантирует, что legacy vault DB wrappers удалены и не реинтродуцированы.
    """
    current_test = Path(__file__).resolve()
    violations: list[str] = []
    for root in (CONNECTOR_ROOT, TESTS_ROOT):
        for path in _py_files(root):
            if path.resolve() == current_test:
                continue
            content = path.read_text(encoding="utf-8")
            if "VaultSqliteDb" in content:
                violations.append(f"{_rel(path)}: VaultSqliteDb")
            if "openVaultDb" in content:
                violations.append(f"{_rel(path)}: openVaultDb")
    assert violations == [], (
        "VaultSqliteDb/openVaultDb must not exist in the repo:\n" + "\n".join(violations)
    )


def test_cache_db_module_is_removed() -> None:
    """
    openCacheDb отсутствует в репозитории.

    Гарантирует, что legacy cache DB opener удалён и не реинтродуцирован.
    """
    current_test = Path(__file__).resolve()
    violations: list[str] = []
    for root in (CONNECTOR_ROOT, TESTS_ROOT):
        for path in _py_files(root):
            if path.resolve() == current_test:
                continue
            content = path.read_text(encoding="utf-8")
            if "openCacheDb" in content:
                violations.append(_rel(path))
    assert violations == [], (
        "openCacheDb must not exist in the repo:\n" + "\n".join(violations)
    )
