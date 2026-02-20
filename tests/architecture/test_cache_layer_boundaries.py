"""
Architecture guard tests for cache boundaries.

Why these tests exist:
1. Protect clean architecture boundaries (domain/usecases must not depend on infra cache).
2. Keep SqliteCacheGateway creation/import in wiring/infra only.
3. Prevent accidental reintroduction of legacy factory imports.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
DOMAIN_ROOT = REPO_ROOT / "connector" / "domain"
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"
TESTS_ROOT = REPO_ROOT / "tests"


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append(module)
    return imports


def _import_froms(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            imports.append((module, names))
    return imports


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    bad: list[str] = []
    for path in _py_files(root):
        rel = path.relative_to(REPO_ROOT)
        for module in _imports(path):
            if module.startswith(forbidden_prefixes):
                bad.append(f"{rel}: {module}")
    return bad


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_allowed_gateway_import_path(path: Path) -> bool:
    rel = _rel(path)
    return (
        rel.startswith("connector/infra/cache/")
        or rel == "connector/delivery/cli/containers.py"
        or rel.startswith("tests/")
    )


def test_domain_does_not_import_infra_cache() -> None:
    violations = _violations(DOMAIN_ROOT, ("connector.infra.cache",))
    assert violations == [], "Forbidden imports found:\n" + "\n".join(violations)


def test_usecases_do_not_import_infra_cache() -> None:
    violations = _violations(USECASES_ROOT, ("connector.infra.cache",))
    assert violations == [], "Forbidden imports found:\n" + "\n".join(violations)


def test_sqlite_gateway_is_imported_only_in_wiring_infra_or_tests() -> None:
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        for module, names in _import_froms(path):
            if module == "connector.infra.cache.cache_gateway" and "SqliteCacheGateway" in names:
                if not _is_allowed_gateway_import_path(path):
                    violations.append(f"{_rel(path)} imports SqliteCacheGateway from infra.gateway")
        for module in _imports(path):
            if module == "connector.infra.cache.cache_gateway":
                if not _is_allowed_gateway_import_path(path):
                    violations.append(f"{_rel(path)} imports connector.infra.cache.cache_gateway")
    assert violations == [], "Forbidden gateway imports found:\n" + "\n".join(violations)


def test_no_legacy_cache_factory_imports() -> None:
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        for module in _imports(path):
            if module.startswith("connector.infra.cache.factory"):
                violations.append(f"{_rel(path)} imports legacy cache factory: {module}")
    for path in _py_files(TESTS_ROOT):
        for module in _imports(path):
            if module.startswith("connector.infra.cache.factory"):
                violations.append(f"{_rel(path)} imports legacy cache factory: {module}")
    assert violations == [], "Legacy factory imports found:\n" + "\n".join(violations)


def test_no_legacy_cache_registry_module() -> None:
    legacy_registry = REPO_ROOT / "connector" / "datasets" / "cache_registry.py"
    assert not legacy_registry.exists(), "Legacy datasets/cache_registry.py must be removed"


def test_no_legacy_dataset_cache_sync_adapters() -> None:
    legacy_paths = [
        REPO_ROOT / "connector" / "datasets" / "employees" / "load" / "cache_sync_adapter.py",
        REPO_ROOT / "connector" / "datasets" / "organizations" / "load" / "cache_sync_adapter.py",
        REPO_ROOT / "connector" / "datasets" / "employees" / "load" / "cache_spec.py",
        REPO_ROOT / "connector" / "datasets" / "organizations" / "load" / "cache_spec.py",
    ]
    existing = [str(path.relative_to(REPO_ROOT)) for path in legacy_paths if path.exists()]
    assert existing == [], "Legacy dataset cache modules must be removed:\n" + "\n".join(existing)
