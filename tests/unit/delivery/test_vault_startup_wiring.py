from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from connector.config.app_settings import (
    ApiSettings,
    AppSettings,
    DatasetSettings,
    ExecutionSettings,
    MatchingRuntimeSettings,
    ObservabilitySettings,
    PathsSettings,
    RefreshSettings,
)
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.delivery.cli.context import CommandContext
from connector.delivery.commands import enrich as enrich_command
from connector.delivery.commands import import_apply as import_apply_command
from connector.delivery.commands import import_plan as import_plan_command
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.secrets.errors import VaultStartupKeyValidationError


class _DummyReport:
    def set_meta(self, **kwargs) -> None:
        _ = kwargs

    def set_context(self, key, value) -> None:
        _ = (key, value)


def _app_settings(tmp_path) -> AppSettings:
    return AppSettings(
        api=ApiSettings(
            host="http://localhost",
            port=443,
            username="u",
            password="p",
            tls_skip_verify=False,
            ca_file=None,
            timeout_seconds=20.0,
            retries=1,
            retry_backoff_seconds=0.1,
            resource_exists_retries=1,
        ),
        paths=PathsSettings(
            cache_dir=str(tmp_path / "cache"),
            log_dir=str(tmp_path / "logs"),
            report_dir=str(tmp_path / "reports"),
        ),
        observability=ObservabilitySettings(
            log_level="INFO",
            log_json=False,
            report_format="json",
            report_items_limit=100,
            report_include_skipped=True,
            diagnostics_strict=True,
        ),
        dataset=DatasetSettings(
            dataset_name="employees",
            csv_has_header=True,
            include_deleted=False,
        ),
        execution=ExecutionSettings(
            stop_on_first_error=False,
            max_actions=None,
            dry_run=True,
        ),
        refresh=RefreshSettings(page_size=100, max_pages=1),
        matching_runtime=MatchingRuntimeSettings(
            match_batch_size=100,
            match_flush_interval_ms=100,
            resolve_batch_size=100,
            resolve_flush_interval_ms=100,
        ),
        resolver=ResolverSettings(
            pending_ttl_seconds=120,
            pending_max_attempts=5,
            pending_sweep_interval_seconds=60,
            pending_on_expire="error",
            pending_allow_partial=False,
            pending_retention_days=14,
        ),
    )


def _ctx(tmp_path) -> CommandContext:
    return CommandContext(
        logger=logging.getLogger("vault-startup-wiring-test"),
        run_id="test-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_settings=_app_settings(tmp_path),
        container=None,
    )


def _startup_error(*, paths_settings) -> None:
    _ = paths_settings
    raise VaultStartupKeyValidationError(details={"reason": "probe_decrypt_failed"})


def _plan() -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="run-1",
            generated_at="now",
            dataset="employees",
            csv_path=None,
            plan_path=None,
            include_deleted=False,
        ),
        summary=PlanSummary(
            rows_total=1,
            valid_rows=1,
            failed_rows=0,
            planned_create=1,
            planned_update=0,
            skipped=0,
        ),
        items=[
            PlanItem(
                row_id="row-1",
                line_no=1,
                op="create",
                target_id="id-1",
                desired_state={"email": "user@example.com"},
                changes={},
                source_ref={"match_key": "mk"},
                secret_fields=[],
            )
        ],
    )


def test_enrich_handler_runs_startup_guard_in_vault_mode(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    container = MagicMock()
    container.sqlite.vault_ready.init.side_effect = VaultStartupKeyValidationError(
        details={"reason": "probe_decrypt_failed"},
    )
    ctx = replace(_ctx(tmp_path), container=container)

    result = enrich_command.handler(
        ctx,
        enrich_command.Options(vault_mode="on"),
        _DummyReport(),
    )

    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}
    assert "VAULT_STARTUP_KEY_VALIDATION_ERROR" in capsys.readouterr().err


def test_import_plan_handler_runs_startup_guard_in_vault_mode(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    container = MagicMock()
    container.sqlite.vault_ready.init.side_effect = VaultStartupKeyValidationError(
        details={"reason": "probe_decrypt_failed"},
    )
    ctx = replace(_ctx(tmp_path), container=container)

    result = import_plan_command.handler(
        ctx,
        import_plan_command.Options(vault_mode="on"),
    )

    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}
    assert "VAULT_STARTUP_KEY_VALIDATION_ERROR" in capsys.readouterr().err


def test_import_apply_handler_runs_startup_guard_in_vault_mode(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    monkeypatch.setattr(import_apply_command, "readPlanFile", lambda _path: _plan())
    container = MagicMock()
    container.sqlite.vault_ready.init.side_effect = VaultStartupKeyValidationError(
        details={"reason": "probe_decrypt_failed"},
    )
    ctx = replace(_ctx(tmp_path), container=container)

    result = import_apply_command.handler(
        ctx,
        import_apply_command.Options(plan_path="dummy-plan.json", vault_mode="on"),
        _DummyReport(),
    )

    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}
    assert "VAULT_STARTUP_KEY_VALIDATION_ERROR" in capsys.readouterr().err
