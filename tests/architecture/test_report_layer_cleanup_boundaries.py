"""
Архитектурные guard-тесты для post-window cleanup report-layer (DEC-002/003/004/005).

Проверяют:
1. Legacy compatibility-файлы удалены и не возвращаются.
2. Runtime не содержит legacy result compatibility (`CliCommandResult/int`).
3. Кодовая база не импортирует удалённые legacy модули report-слоя.
4. Use-cases не импортируют infra-пакеты (RPT-011: clean architecture boundary).
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
USECASES_ROOT = CONNECTOR_ROOT / "usecases"
RUNTIME_RESULT_MAPPER = CONNECTOR_ROOT / "delivery" / "cli" / "runtime" / "result_mapper.py"
RUNTIME_CONTRACTS = CONNECTOR_ROOT / "delivery" / "cli" / "runtime" / "contracts.py"
RUNTIME_ORCHESTRATOR = CONNECTOR_ROOT / "delivery" / "cli" / "runtime" / "orchestrator.py"

# Usecase-файлы, которым временно разрешён infra-импорт (RPT-011, P2 OPEN).
# Когда RPT-011 закроется — убрать исключения и сократить список до пустого.
_RPT011_KNOWN_VIOLATIONS: frozenset[str] = frozenset(
    {
        "connector/usecases/cache_command_service.py",
        "connector/usecases/cache_refresh_service.py",
    }
)

REMOVED_LEGACY_PATHS = (
    "connector/domain/transform/core/result_processor.py",
    "connector/domain/reporting/bridge.py",
    "connector/domain/reporting/ports.py",
    "connector/domain/reporting/collector.py",
    "connector/delivery/cli/result.py",
    "connector/infra/artifacts/report_writer.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "connector.domain.reporting.bridge",
    "connector.domain.reporting.ports",
    "connector.domain.reporting.collector",
    "connector.delivery.cli.result",
    "connector.infra.artifacts.report_writer",
    "connector.domain.transform.core.result_processor",
)

FORBIDDEN_RUNTIME_MARKERS = (
    "CliCommandResult",
    "legacy_cli",
    "legacy_int",
    "adapt_runtime_result",
    "NullReportWritePort",
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


def test_report_legacy_cleanup_files_are_removed() -> None:
    existing = [path for path in REMOVED_LEGACY_PATHS if (REPO_ROOT / path).exists()]
    assert existing == [], "Legacy report-файлы должны быть удалены:\n" + "\n".join(existing)


def test_connector_code_does_not_import_removed_report_legacy_modules() -> None:
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        rel = _rel(path)
        for module in _imports(path):
            if any(_is_forbidden_import(module, forbidden) for forbidden in FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{rel}: {module}")
    assert violations == [], "Найдены запрещённые legacy-импорты:\n" + "\n".join(violations)


def test_runtime_boundary_has_no_legacy_result_markers() -> None:
    files = (RUNTIME_RESULT_MAPPER, RUNTIME_CONTRACTS, RUNTIME_ORCHESTRATOR)
    violations: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_RUNTIME_MARKERS:
            if marker in source:
                violations.append(f"{_rel(path)}: {marker}")
    assert violations == [], "Runtime boundary содержит legacy-маркеры:\n" + "\n".join(violations)


def _is_forbidden_import(module: str, forbidden: str) -> bool:
    return module == forbidden or module.startswith(f"{forbidden}.")


# ---------------------------------------------------------------------------
# RPT-011: Use-case → infra boundary
# ---------------------------------------------------------------------------

def test_usecases_do_not_import_infra() -> None:
    """Use-case слой не должен импортировать из connector.infra.*

    Единственные разрешённые исключения — файлы из _RPT011_KNOWN_VIOLATIONS
    (задокументированный техдолг P2 до закрытия RPT-011).
    """
    violations: list[str] = []
    for path in _py_files(USECASES_ROOT):
        rel = _rel(path)
        if rel in _RPT011_KNOWN_VIOLATIONS:
            continue
        for module in _imports(path):
            if _is_forbidden_import(module, "connector.infra"):
                violations.append(f"{rel}: {module}")
    assert violations == [], (
        "Use-cases импортируют из connector.infra (нарушение clean architecture):\n"
        + "\n".join(violations)
    )


def test_rpt011_known_violations_are_still_tracked() -> None:
    """Явная проверка: файлы из списка RPT-011 действительно нарушают границу.

    Если нарушение исправят — тест сломается, напомнив убрать запись из allowlist.
    """
    still_violating = []
    for rel in _RPT011_KNOWN_VIOLATIONS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        if any(
            _is_forbidden_import(m, "connector.infra") for m in _imports(path)
        ):
            still_violating.append(rel)
    assert set(still_violating) == _RPT011_KNOWN_VIOLATIONS, (
        "Список RPT011_KNOWN_VIOLATIONS устарел. "
        "Убери исправленные файлы из allowlist:\n"
        + "\n".join(sorted(_RPT011_KNOWN_VIOLATIONS - set(still_violating)))
    )
