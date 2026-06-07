"""
Архитектурные guard-тесты для planning-пайплайна.

Зачем нужны эти тесты:
1. Гарантировать, что ImportPlanService и PlanUseCase удалены (DEC-002).
2. Убедиться, что PendingReplayPort удалён из roles.py (DEC-001).
3. Убедиться, что pending_codec не тянет infra в domain.
4. Гарантировать, что plan_writer не маскирует секреты через maskSecretsInObject.
5. Гарантировать, что usecases не импортируют connector.infra.*.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append(node.module or "")
    return result


def _import_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.extend(alias.name for alias in node.names)
    return names


def _class_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


# ---------------------------------------------------------------------------
# Guards: удалённые модули
# ---------------------------------------------------------------------------


def test_import_plan_service_module_removed() -> None:
    path = USECASES_ROOT / "import_plan_service.py"
    assert not path.exists(), (
        "import_plan_service.py должен быть удалён (PLANNER-DEC-002)"
    )


def test_plan_usecase_module_removed() -> None:
    path = USECASES_ROOT / "plan_usecase.py"
    assert not path.exists(), "plan_usecase.py должен быть удалён (PLANNER-DEC-002)"


def test_planning_match_runtime_moved_to_delivery() -> None:
    path = USECASES_ROOT / "planning_match_runtime.py"
    assert not path.exists(), (
        "planning_match_runtime.py должен быть в connector/delivery/cli/, не в usecases/ (TRANSFORM-DEC-006)"
    )


def test_import_plan_does_not_import_orchestrator_symbols() -> None:
    path = REPO_ROOT / "connector" / "delivery" / "commands" / "import_plan.py"
    imports = _imports(path)
    forbidden = {
        "connector.domain.transform.stages.stages",
        "connector.usecases.planning_match_runtime",
        "connector.usecases.resolve_usecase",
    }
    violations = [m for m in imports if m in forbidden]
    assert violations == [], (
        "import_plan.py не должен знать о стадиях и match lifecycle (TRANSFORM-DEC-006):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Guard: PendingReplayPort удалён из roles.py
# ---------------------------------------------------------------------------


def test_pending_replay_port_removed_from_roles() -> None:
    roles_path = REPO_ROOT / "connector" / "domain" / "ports" / "cache" / "roles.py"
    assert roles_path.exists(), f"roles.py не найден: {roles_path}"
    class_names = _class_names(roles_path)
    assert "PendingReplayPort" not in class_names, (
        "PendingReplayPort не должен быть в roles.py (PLANNER-DEC-001)"
    )


# ---------------------------------------------------------------------------
# Guard: pending_codec не тянет infra
# ---------------------------------------------------------------------------


def test_pending_codec_has_no_infra_imports() -> None:
    codec_path = (
        REPO_ROOT
        / "connector"
        / "domain"
        / "transform"
        / "resolver"
        / "pending_codec.py"
    )
    assert codec_path.exists(), f"pending_codec.py не найден: {codec_path}"
    violations = [m for m in _imports(codec_path) if m.startswith("connector.infra")]
    assert violations == [], (
        "pending_codec.py не должен импортировать connector.infra.*:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Guard: plan_writer не маскирует через maskSecretsInObject
# ---------------------------------------------------------------------------


def test_plan_writer_does_not_mask_secrets() -> None:
    writer_path = REPO_ROOT / "connector" / "infra" / "artifacts" / "plan_writer.py"
    assert writer_path.exists(), f"plan_writer.py не найден: {writer_path}"
    forbidden = {"maskSecretsInObject", "mask_secrets"}
    violations = [n for n in _import_names(writer_path) if n in forbidden]
    assert violations == [], (
        "plan_writer.py не должен импортировать функции маскирования:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Guard: usecases не импортируют infra
# ---------------------------------------------------------------------------

_KNOWN_INFRA_VIOLATIONS: frozenset[str] = frozenset()


def test_usecases_do_not_import_infra() -> None:
    violations: list[str] = []
    for path in USECASES_ROOT.glob("*.py"):
        for module in _imports(path):
            if module.startswith("connector.infra"):
                rel = str(path.relative_to(REPO_ROOT))
                entry = f"{rel}: {module}"
                if entry not in _KNOWN_INFRA_VIOLATIONS:
                    violations.append(entry)
    assert violations == [], (
        "connector/usecases/*.py не должны импортировать connector.infra.* "
        "(за исключением зафиксированных pre-existing нарушений):\n"
        + "\n".join(violations)
    )
