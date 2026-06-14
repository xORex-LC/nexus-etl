"""Архитектурные guard-тесты для границ observability logging layer."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml

from connector.common.observability import (
    ObservabilityEvent,
    ObservabilityEventSink,
    PipelineLifecycleEvents,
    RuntimeLifecycleEvents,
)
from connector.infra.logging.ecs import STRUCTURAL_ROOTS

pytestmark = pytest.mark.architecture

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
COMMON_OBSERVABILITY_ROOT = CONNECTOR_ROOT / "common" / "observability"
TAXONOMY_FIELDS_ROOT = COMMON_OBSERVABILITY_ROOT / "taxonomy" / "fields"

EXPECTED_STRUCTURAL_ROOTS = frozenset(
    {
        "@timestamp",
        "component",
        "ecs",
        "error",
        "event",
        "exception",
        "file",
        "host",
        "http",
        "labels",
        "log",
        "message",
        "nexus",
        "process",
        "service",
        "span",
        "tags",
        "trace",
        "url",
    }
)

ALLOWED_ECS_TRANSFORM_IMPORTS = {
    "connector/infra/logging/runtime.py",
}


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def _import_froms(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            result.append((node.module or "", [alias.name for alias in node.names]))
    return result


def _field_entries() -> list[tuple[Path, dict[str, Any]]]:
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(TAXONOMY_FIELDS_ROOT.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries.extend((path, entry) for entry in payload.get("fields") or ())
    return entries


def test_event_contracts_live_in_common_observability() -> None:
    assert ObservabilityEvent.__module__ == "connector.common.observability.events"
    assert ObservabilityEventSink.__module__ == "connector.common.observability.ports"
    assert RuntimeLifecycleEvents.__module__ == "connector.common.observability.ports"
    assert PipelineLifecycleEvents.__module__ == "connector.common.observability.ports"


def test_common_observability_contracts_do_not_import_infra_or_delivery() -> None:
    violations: list[str] = []
    for path in _python_files(COMMON_OBSERVABILITY_ROOT):
        if "taxonomy" in path.parts:
            continue
        for module in _imports(path):
            if module.startswith(("connector.infra", "connector.delivery")):
                violations.append(f"{_rel(path)}: {module}")
            if module in {"structlog", "logging"}:
                violations.append(f"{_rel(path)}: {module}")

    assert violations == [], (
        "common observability contracts must stay runtime-neutral:\n"
        + "\n".join(violations)
    )


def test_ecs_transform_is_imported_only_by_logging_runtime() -> None:
    violations: list[str] = []
    for path in _python_files(CONNECTOR_ROOT):
        rel = _rel(path)
        if (
            rel in ALLOWED_ECS_TRANSFORM_IMPORTS
            or rel == "connector/infra/logging/ecs.py"
        ):
            continue
        for module, names in _import_froms(path):
            if module == "connector.infra.logging.ecs" and "ecs_transform" in names:
                violations.append(f"{rel}: from {module} import ecs_transform")

    assert violations == [], (
        "ecs_transform must remain the final logging runtime processor:\n"
        + "\n".join(violations)
    )


def test_reserved_structural_roots_are_complete_and_explicit() -> None:
    assert STRUCTURAL_ROOTS == EXPECTED_STRUCTURAL_ROOTS


def test_taxonomy_field_roots_are_allowed_structural_roots() -> None:
    violations: list[str] = []
    for path, entry in _field_entries():
        key = str(entry["key"])
        root = key.split(".", 1)[0] if key != "@timestamp" else "@timestamp"
        if root not in EXPECTED_STRUCTURAL_ROOTS:
            violations.append(f"{_rel(path)}: {key}")

    assert violations == [], (
        "taxonomy field keys must use approved ECS/project roots:\n"
        + "\n".join(violations)
    )


def test_taxonomy_field_aliases_are_short_unique_names() -> None:
    aliases: dict[str, str] = {}
    violations: list[str] = []
    for path, entry in _field_entries():
        key = str(entry["key"])
        for raw_alias in entry.get("aliases") or ():
            alias = str(raw_alias)
            previous = aliases.setdefault(alias, key)
            if previous != key:
                violations.append(f"{alias}: {previous} / {key}")
            if "." in alias:
                violations.append(f"{_rel(path)}: alias must not be dotted: {alias}")

    assert violations == [], (
        "taxonomy aliases must be short, unique names:\n" + "\n".join(violations)
    )
