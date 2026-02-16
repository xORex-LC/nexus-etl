from __future__ import annotations

from connector.config.config import Settings, _validate_settings


def test_validate_settings_collects_range_enum_and_conflict_issues():
    settings = Settings(
        page_size=0,
        retries=-1,
        match_batch_size=0,
        resolve_batch_size=0,
        pending_ttl_seconds=0,
        pending_on_expire="bad-value",
        target_runtime_mode="broken",
        host="127.0.0.1",
        port=None,
    )

    issues = _validate_settings(settings)
    codes = {issue.code for issue in issues}
    fields = {issue.field_path for issue in issues}

    assert "settings.validation.range" in codes
    assert "settings.validation.enum" in codes
    assert "settings.conflict.api_credentials" in codes
    assert {"page_size", "retries", "match_batch_size", "resolve_batch_size", "pending_ttl_seconds"} <= fields
    assert "pending_on_expire" in fields
    assert "target_runtime_mode" in fields
    assert "host/port" in fields
