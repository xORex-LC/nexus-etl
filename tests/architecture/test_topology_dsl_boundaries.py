"""Архитектурные guard-тесты для topology DSL/runtime границы."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from pydantic import BaseModel

from connector.domain.dependency_tree import TopologyNode, TopologySnapshot
from connector.domain.ports.topology import (
    SourceTopologyCanonicalPath,
    TargetHierarchyRow,
)
from connector.domain.transform_dsl.specs import TopologySpec

pytestmark = pytest.mark.architecture

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDENCY_TREE_ROOT = REPO_ROOT / "connector" / "domain" / "dependency_tree"
TOPOLOGY_PORTS_ROOT = REPO_ROOT / "connector" / "domain" / "ports" / "topology"


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


def test_runtime_topology_modules_do_not_import_pydantic() -> None:
    violations: list[str] = []
    for root in (DEPENDENCY_TREE_ROOT, TOPOLOGY_PORTS_ROOT):
        for path in _py_files(root):
            rel = path.relative_to(REPO_ROOT)
            for module in _imports(path):
                if module == "pydantic" or module.startswith("pydantic."):
                    violations.append(f"{rel}: {module}")
    assert violations == [], (
        "Runtime topology modules must not depend on Pydantic:\n"
        + "\n".join(violations)
    )


def test_topology_runtime_contracts_are_dataclasses_not_basemodels() -> None:
    assert dataclasses.is_dataclass(TopologyNode)
    assert dataclasses.is_dataclass(TopologySnapshot)
    assert dataclasses.is_dataclass(SourceTopologyCanonicalPath)
    assert dataclasses.is_dataclass(TargetHierarchyRow)
    assert not issubclass(TopologyNode, BaseModel)
    assert not issubclass(TopologySnapshot, BaseModel)


def test_topology_spec_boundary_uses_pydantic_models() -> None:
    assert issubclass(TopologySpec, BaseModel)
