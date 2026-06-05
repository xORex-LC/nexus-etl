"""
Тесты ownership-policy для report meta (DEC-006).

Проверяют:
1. `items_limit` выставляется только runtime-слоем.
2. `dataset` заполняется только dataset-aware handler-ами.
3. В usecase/service слое нет записи `report.set_meta(...)`.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from connector.common.observability import ServiceComponent
from connector.config.models import AppConfig
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli import runtime as runtime_module
from connector.domain.diagnostics import build_catalog
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.events import SetMetaEvent


@dataclass
class _OverrideProbe:
    value: object | None = None

    def override(self, value: object) -> None:
        self.value = value


class _FakeContainer:
    def __init__(self) -> None:
        self.app_config = _OverrideProbe()
        self.target = SimpleNamespace(transport=_OverrideProbe())

    def shutdown_resources(self) -> None:
        return None


def _patch_fake_observability(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Подменить observability session для ownership-policy тестов."""
    session = SimpleNamespace(
        component=ServiceComponent.MAPPER,
        layout=object(),
        runtime=SimpleNamespace(
            redaction_engine=SimpleNamespace(redact_text=lambda value: value)
        ),
        logger=logging.getLogger("report-meta-fake-observability"),
        log_file_path=str(tmp_path / "logs" / "mapping.log"),
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_initialize_observability_session",
        lambda **_: session,
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_run_observability_sweeper",
        lambda **_: None,
    )


def _app_config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "api": {
                "host": "http://localhost",
                "port": 443,
                "username": "u",
                "password": "p",
                "retries": 1,
                "retry_backoff_seconds": 0.1,
                "resource_exists_retries": 1,
            },
            "paths": {
                "cache_dir": str(tmp_path / "cache"),
                "log_dir": str(tmp_path / "logs"),
                "report_dir": str(tmp_path / "reports"),
            },
            "observability": {
                "logging": {"level": "INFO"},
                "reporting": {"items_limit": 100},
                "diagnostics": {"strict": True},
            },
            "dataset": {"dataset_name": "employees"},
            "execution": {"dry_run": True},
            "refresh": {"page_size": 100, "max_pages": 1},
            "matching_runtime": {
                "match_batch_size": 100,
                "match_flush_interval_ms": 100,
            },
            "resolver": {"resolve_batch_size": 100, "resolve_flush_interval_ms": 100},
        }
    )


def _ctx(tmp_path: Path) -> UnboundCommandContext:
    return CommandContext(
        logger=logging.getLogger("report-meta-ownership-policy-test"),
        run_id="ownership-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_config=_app_config(tmp_path),
        container=None,
    )


def _run_and_build_report(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    command_name: str,
    opts,
    handler,
):
    captured: dict[str, object] = {}

    def _capture_finalize(**kwargs):
        captured["report_assembler"] = kwargs["report_assembler"]
        return None

    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: _FakeContainer())
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(
        runtime_module, "_shutdown_container_resources", lambda **_: None
    )
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _capture_finalize)

    runtime_module.run_with_report(
        ctx=_ctx(tmp_path),
        command_name=command_name,
        opts=opts,
        handler=handler,
        requirements=Requirements(),
    )

    assembler = captured.get("report_assembler")
    assert isinstance(assembler, ReportAssembler)
    return assembler.assemble()


def test_runtime_is_owner_of_items_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _run_and_build_report(
        monkeypatch,
        tmp_path=tmp_path,
        command_name="mapping",
        opts=SimpleNamespace(report_items_limit=17),
        handler=lambda _ctx, _opts, _report: None,
    )

    assert built.meta.items_limit == 17


def test_dataset_agnostic_command_report_keeps_dataset_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    built = _run_and_build_report(
        monkeypatch,
        tmp_path=tmp_path,
        command_name="check_api",
        opts=SimpleNamespace(dataset="employees"),
        handler=lambda _ctx, _opts, _report: None,
    )

    assert built.meta.dataset is None


def test_dataset_aware_handler_owns_dataset_meta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _dataset_handler(_ctx, _opts, report_sink):
        report_sink.emit(SetMetaEvent(dataset="employees"))
        return None

    built = _run_and_build_report(
        monkeypatch,
        tmp_path=tmp_path,
        command_name="mapping",
        opts=SimpleNamespace(),
        handler=_dataset_handler,
    )

    assert built.meta.dataset == "employees"


def test_architecture_guards_report_meta_ownership() -> None:
    project_root = Path(__file__).resolve().parents[3]
    usecases_root = project_root / "connector" / "usecases"
    commands_root = project_root / "connector" / "delivery" / "commands"
    runtime_file = (
        project_root / "connector" / "delivery" / "cli" / "runtime" / "orchestrator.py"
    )

    usecase_violations: list[str] = []
    command_items_limit_violations: list[str] = []
    runtime_items_limit_calls = 0

    for path in usecases_root.rglob("*.py"):
        if _has_report_set_meta_call(path):
            usecase_violations.append(str(path.relative_to(project_root)))

    for path in commands_root.rglob("*.py"):
        for call in _iter_set_meta_event_calls(path):
            if _call_has_kw(call, "items_limit"):
                command_items_limit_violations.append(
                    str(path.relative_to(project_root))
                )
                break

    for call in _iter_set_meta_event_calls(runtime_file):
        if _call_has_kw(call, "items_limit"):
            runtime_items_limit_calls += 1

    assert usecase_violations == []
    assert command_items_limit_violations == []
    assert runtime_items_limit_calls == 1


def _has_report_set_meta_call(path: Path) -> bool:
    return any(True for _ in _iter_report_set_meta_calls(path))


def _iter_report_set_meta_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "set_meta":
            continue
        target = func.value
        if isinstance(target, ast.Name) and target.id == "report":
            yield node


def _iter_set_meta_event_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "SetMetaEvent":
            yield node


def _call_has_kw(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in call.keywords)
