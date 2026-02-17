"""
Архитектурные guard-тесты для границ apply use-case.

Зачем нужны эти тесты:
1. Гарантировать, что connector/usecases/*apply* не импортирует infra/delivery.
2. Убедиться, что use-case не зависит от ReportCollector, logEvent и maskSecrets.
3. Предотвратить повторное смешение presentation/infra с бизнес-логикой.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
USECASES_APPLY_ROOT = REPO_ROOT / "connector" / "usecases" / "apply"
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"


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


def _import_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.append(alias.name)
    return names


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


# --- Тесты ---


def test_apply_usecase_does_not_import_infra() -> None:
    violations = _violations(USECASES_APPLY_ROOT, ("connector.infra",))
    assert violations == [], "Apply use-case импортирует infra:\n" + "\n".join(violations)


def test_apply_usecase_does_not_import_delivery() -> None:
    violations = _violations(USECASES_APPLY_ROOT, ("connector.delivery",))
    assert violations == [], "Apply use-case импортирует delivery:\n" + "\n".join(violations)


def test_import_apply_service_does_not_import_infra() -> None:
    service_path = USECASES_ROOT / "import_apply_service.py"
    if not service_path.exists():
        return
    violations: list[str] = []
    for module in _imports(service_path):
        if module.startswith("connector.infra"):
            violations.append(f"{_rel(service_path)}: {module}")
    assert violations == [], "ImportApplyService импортирует infra:\n" + "\n".join(violations)


def test_import_apply_service_does_not_import_delivery() -> None:
    service_path = USECASES_ROOT / "import_apply_service.py"
    if not service_path.exists():
        return
    violations: list[str] = []
    for module in _imports(service_path):
        if module.startswith("connector.delivery"):
            violations.append(f"{_rel(service_path)}: {module}")
    assert violations == [], "ImportApplyService импортирует delivery:\n" + "\n".join(violations)


def test_import_apply_service_does_not_import_datasets() -> None:
    service_path = USECASES_ROOT / "import_apply_service.py"
    if not service_path.exists():
        return
    violations: list[str] = []
    for module in _imports(service_path):
        if module.startswith("connector.datasets"):
            violations.append(f"{_rel(service_path)}: {module}")
    assert violations == [], "ImportApplyService импортирует datasets:\n" + "\n".join(violations)


def test_usecase_does_not_use_report_collector() -> None:
    violations: list[str] = []
    for path in [USECASES_ROOT / "import_apply_service.py", *_py_files(USECASES_APPLY_ROOT)]:
        if not path.exists():
            continue
        for name in _import_names(path):
            if name == "ReportCollector":
                violations.append(f"{_rel(path)} imports ReportCollector")
    assert violations == [], "Use-case не должен зависеть от ReportCollector:\n" + "\n".join(violations)


def test_usecase_does_not_use_logEvent() -> None:
    violations: list[str] = []
    for path in [USECASES_ROOT / "import_apply_service.py", *_py_files(USECASES_APPLY_ROOT)]:
        if not path.exists():
            continue
        for name in _import_names(path):
            if name == "logEvent":
                violations.append(f"{_rel(path)} imports logEvent")
    assert violations == [], "Use-case не должен зависеть от logEvent:\n" + "\n".join(violations)


def test_usecase_does_not_use_maskSecrets() -> None:
    violations: list[str] = []
    for path in [USECASES_ROOT / "import_apply_service.py", *_py_files(USECASES_APPLY_ROOT)]:
        if not path.exists():
            continue
        for name in _import_names(path):
            if name in ("maskSecretsInObject", "mask_secrets"):
                violations.append(f"{_rel(path)} imports {name}")
    assert violations == [], "Use-case не должен зависеть от маскирования секретов:\n" + "\n".join(violations)


def test_resolve_primary_code_deterministic_with_multiple_fatal() -> None:
    """Fix 5: resolve_primary_code должен быть детерминированным при нескольких fatal-кодах."""
    from connector.domain.diagnostics.policies import (
        SystemErrorCode,
        StopPolicy,
        FATAL_CODES,
        resolve_primary_code,
    )
    stop = StopPolicy(fatal=FATAL_CODES)
    codes = {SystemErrorCode.AUTH_UNAUTHORIZED, SystemErrorCode.INTERNAL_ERROR}
    results = set()
    for _ in range(100):
        results.add(resolve_primary_code(codes, stop))
    assert len(results) == 1, f"resolve_primary_code недетерминирован: {results}"
    assert results.pop() == SystemErrorCode.INTERNAL_ERROR


def test_resolve_primary_code_respects_custom_stop_policy() -> None:
    from connector.domain.diagnostics.policies import (
        SystemErrorCode,
        StopPolicy,
        resolve_primary_code,
    )

    stop = StopPolicy(fatal=frozenset({SystemErrorCode.AUTH_FORBIDDEN}))
    codes = {SystemErrorCode.AUTH_FORBIDDEN, SystemErrorCode.INTERNAL_ERROR}

    assert resolve_primary_code(codes, stop) == SystemErrorCode.AUTH_FORBIDDEN


def test_resolve_primary_code_handles_custom_fatal_outside_default_priority() -> None:
    from connector.domain.diagnostics.policies import (
        SystemErrorCode,
        StopPolicy,
        resolve_primary_code,
    )

    stop = StopPolicy(fatal=frozenset({SystemErrorCode.INFRA_UNAVAILABLE}))
    codes = {SystemErrorCode.DATA_INVALID, SystemErrorCode.INFRA_UNAVAILABLE}

    assert resolve_primary_code(codes, stop) == SystemErrorCode.INFRA_UNAVAILABLE
