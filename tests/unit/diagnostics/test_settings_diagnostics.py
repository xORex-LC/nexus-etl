from __future__ import annotations

from connector.config.config import SettingsIssue, SettingsLoadError
from connector.config.diagnostics import translate_settings_load_error, translate_settings_warnings
from connector.domain.diagnostics import build_catalog
from connector.domain.models import DiagnosticSeverity, DiagnosticStage


def test_translate_settings_load_error_to_diagnostics() -> None:
    catalog = build_catalog(None, strict=True)
    err = SettingsLoadError(
        "invalid settings",
        [
            SettingsIssue(
                code="settings.parse.invalid_value",
                field_path="retries",
                source="config",
                raw_value="abc",
                message="invalid int",
                hint="use integer",
            )
        ],
    )

    diagnostics = translate_settings_load_error(
        catalog=catalog,
        stage=DiagnosticStage.SINK,
        error=err,
    )

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "settings.parse.invalid_value"
    assert diag.field == "retries"
    assert diag.message == "invalid int"
    assert diag.severity == DiagnosticSeverity.ERROR
    assert diag.details == {"source": "config", "raw_value": "abc", "hint": "use integer"}


def test_translate_settings_warnings_produces_warning_severity() -> None:
    catalog = build_catalog(None, strict=True)
    warnings = [
        SettingsIssue(
            code="settings.unknown_key",
            field_path="unknown",
            source="config",
            raw_value=123,
            message="unknown key",
            hint="remove key",
        )
    ]

    diagnostics = translate_settings_warnings(
        catalog=catalog,
        stage=DiagnosticStage.SINK,
        warnings=warnings,
    )

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "settings.unknown_key"
    assert diag.severity == DiagnosticSeverity.WARNING
