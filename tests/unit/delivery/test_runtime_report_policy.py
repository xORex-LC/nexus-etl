from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from connector.config.models import AppConfig
from connector.delivery.cli import runtime as runtime_module
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.domain.diagnostics import build_catalog


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


def _app_config(tmp_path: Path, *, profile: str) -> AppConfig:
    return AppConfig.model_validate({
        "api": {"host": "http://localhost", "port": 443, "username": "u", "password": "p",
                "retries": 1, "retry_backoff_seconds": 0.1, "resource_exists_retries": 1},
        "paths": {"cache_dir": str(tmp_path / "cache"), "log_dir": str(tmp_path / "logs"),
                  "report_dir": str(tmp_path / "reports")},
        "observability": {
            "log_level": "INFO",
            "report_items_limit": 100,
            "report_include_skipped": True,
            "report_policy_profile": profile,
            "diagnostics_strict": True,
        },
        "dataset": {"dataset_name": "employees", "csv_has_header": True},
        "execution": {"dry_run": True},
        "refresh": {"page_size": 100, "max_pages": 1},
        "matching_runtime": {"match_batch_size": 100, "match_flush_interval_ms": 100},
        "resolver": {"resolve_batch_size": 100, "resolve_flush_interval_ms": 100},
    })


def _ctx(tmp_path: Path, *, profile: str) -> UnboundCommandContext:
    return CommandContext(
        logger=logging.getLogger("runtime-report-policy-test"),
        run_id="policy-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_config=_app_config(tmp_path, profile=profile),
        container=None,
    )


def _run_with_capture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    profile: str,
    report_include_skipped: bool | None,
):
    captured: dict[str, object] = {}

    def _capture_finalize(**kwargs):
        captured["report"] = kwargs["report"]
        return None

    monkeypatch.setattr(runtime_module, "AppContainer", lambda: _FakeContainer())
    monkeypatch.setattr(runtime_module, "_initialize_container_resources", lambda **_: None)
    monkeypatch.setattr(runtime_module, "_shutdown_container_resources", lambda **_: None)
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _capture_finalize)

    runtime_module.run_with_report(
        ctx=_ctx(tmp_path, profile=profile),
        command_name="import-plan",
        opts=SimpleNamespace(report_include_skipped=report_include_skipped),
        handler=lambda _ctx, _opts, _report: None,
        requirements=Requirements(),
    )
    report = captured["report"]
    return report.build().context["report_policy"]


@pytest.mark.parametrize(
    ("profile", "cli_override", "expected"),
    [
        ("minimal", True, False),
        ("minimal", False, False),
        ("standard", True, True),
        ("standard", False, False),
        ("debug", True, True),
        ("debug", False, False),
    ],
)
def test_runtime_policy_effective_include_skipped_follows_capability_and_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
    cli_override: bool,
    expected: bool,
) -> None:
    policy_context = _run_with_capture(
        monkeypatch,
        tmp_path=tmp_path,
        profile=profile,
        report_include_skipped=cli_override,
    )

    assert policy_context["profile"] == profile
    assert policy_context["cli_include_skipped"] is cli_override
    assert policy_context["effective_include_skipped_items"] is expected


def test_runtime_and_reporting_do_not_compare_profile_literals_inline() -> None:
    project_root = Path(__file__).resolve().parents[3]
    runtime_path = project_root / "connector" / "delivery" / "cli" / "runtime_orchestrator.py"
    reporter_path = project_root / "connector" / "domain" / "reporting" / "adapters" / "stage_result_reporter.py"
    profile_literals = {"minimal", "standard", "debug"}

    assert _has_profile_literal_comparison(runtime_path, profile_literals) is False
    assert _has_profile_literal_comparison(reporter_path, profile_literals) is False


def _has_profile_literal_comparison(path: Path, profile_literals: set[str]) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                if operand.value in profile_literals:
                    return True
    return False

