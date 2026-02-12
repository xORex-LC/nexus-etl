from __future__ import annotations

from connector.config.config import SettingsIssue
from connector.config.diagnostics import translate_settings_issue
from connector.domain.diagnostics import build_catalog
from connector.domain.models import DiagnosticSeverity, DiagnosticStage


def test_translate_settings_issue_as_error():
    catalog = build_catalog(None, strict=True)
    issue = SettingsIssue(
        code="settings.parse.invalid_value",
        field_path="retries",
        source="env",
        raw_value="bad",
        message="invalid int",
        hint="use integer",
    )

    diag = translate_settings_issue(
        catalog=catalog,
        stage=DiagnosticStage.SINK,
        issue=issue,
        as_warning=False,
    )

    assert diag.code == "settings.parse.invalid_value"
    assert diag.field == "retries"
    assert diag.severity == DiagnosticSeverity.ERROR
    assert diag.details == {"source": "env", "raw_value": "bad", "hint": "use integer"}


def test_translate_settings_issue_as_warning():
    catalog = build_catalog(None, strict=True)
    issue = SettingsIssue(
        code="settings.unknown_key",
        field_path="unknown",
        source="config",
        raw_value=123,
        message="unknown key",
        hint="remove key",
    )

    diag = translate_settings_issue(
        catalog=catalog,
        stage=DiagnosticStage.SINK,
        issue=issue,
        as_warning=True,
    )

    assert diag.code == "settings.unknown_key"
    assert diag.field == "unknown"
    assert diag.severity == DiagnosticSeverity.WARNING
    assert diag.details == {"source": "config", "raw_value": 123, "hint": "remove key"}
