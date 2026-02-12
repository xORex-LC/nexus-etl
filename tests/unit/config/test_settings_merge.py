from __future__ import annotations

from dataclasses import asdict

from connector.config.config import Settings, _apply_source, _build_field_specs


def _trace_defaults() -> dict[str, str]:
    return {spec.name: "default" for spec in _build_field_specs()}


def _specs_by_name():
    specs = _build_field_specs()
    return {spec.name: spec for spec in specs}


def test_apply_source_priority_and_trace():
    merged = asdict(Settings())
    source_trace = _trace_defaults()
    specs_by_name = _specs_by_name()
    issues = []

    _apply_source(
        source_name="config",
        raw_values={"retries": 1, "include_deleted": True},
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=False,
        issues=issues,
    )
    _apply_source(
        source_name="env",
        raw_values={"retries": "2", "include_deleted": "1"},
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=True,
        issues=issues,
    )
    _apply_source(
        source_name="cli",
        raw_values={"retries": 3, "include_deleted": False},
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=True,
        issues=issues,
    )

    assert issues == []
    assert merged["retries"] == 3
    assert merged["include_deleted"] is False
    assert source_trace["retries"] == "cli"
    assert source_trace["include_deleted"] == "cli"


def test_apply_source_skip_none_does_not_override():
    merged = asdict(Settings(retries=9, include_deleted=False))
    source_trace = _trace_defaults()
    specs_by_name = _specs_by_name()
    issues = []

    _apply_source(
        source_name="env",
        raw_values={"retries": None, "include_deleted": None},
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=True,
        issues=issues,
    )

    assert issues == []
    assert merged["retries"] == 9
    assert merged["include_deleted"] is False
    assert source_trace["retries"] == "default"
    assert source_trace["include_deleted"] == "default"
