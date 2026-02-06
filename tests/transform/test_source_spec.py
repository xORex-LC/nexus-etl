from __future__ import annotations

from connector.domain.transform.dsl.loader import load_source_spec_for_dataset, resolve_source_location


def test_load_source_spec_for_dataset() -> None:
    spec = load_source_spec_for_dataset("employees")
    assert spec.dataset == "employees"
    assert spec.source.type == "file"
    assert spec.source.format == "csv"
    assert spec.source.location_ref == "EMPLOYEES_SOURCE_PATH"


def test_resolve_source_location_from_env(monkeypatch) -> None:
    monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", "/tmp/employees.csv")
    spec = load_source_spec_for_dataset("employees")
    assert resolve_source_location(spec) == "/tmp/employees.csv"


def test_resolve_source_location_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("EMPLOYEES_SOURCE_PATH", raising=False)
    spec = load_source_spec_for_dataset("employees")
    try:
        resolve_source_location(spec)
    except ValueError as exc:
        assert "source location is not configured" in str(exc)
        return
    raise AssertionError("ValueError was not raised")
