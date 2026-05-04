from __future__ import annotations

import pytest

from connector.domain.transform_dsl import load_source_spec_for_dataset, resolve_source_location
from connector.domain.transform_dsl.specs import SourceSpec


def test_load_source_spec_for_dataset(employees_registry_path) -> None:
    spec = load_source_spec_for_dataset("employees")
    assert spec.dataset == "employees"
    assert spec.source.type == "file"
    assert spec.source.format == "csv"
    assert spec.source.location_ref == "EMPLOYEES_SOURCE_PATH"
    csv_options = spec.source.csv_options()
    assert csv_options.delimiter
    assert csv_options.encoding


def test_source_spec_csv_options_default_to_current_runtime_values() -> None:
    spec = SourceSpec.model_validate(
        {
            "dataset": "employees",
            "source": {
                "type": "file",
                "format": "csv",
                "location": "/tmp/employees.csv",
            },
        }
    )

    csv_options = spec.source.csv_options()

    assert csv_options.delimiter == ","
    assert csv_options.encoding == "utf-8-sig"


def test_source_spec_rejects_invalid_csv_delimiter() -> None:
    with pytest.raises(ValueError, match="CSV delimiter must be exactly one character"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": "csv",
                    "location": "/tmp/employees.csv",
                    "options": {
                        "delimiter": ";;",
                        "encoding": "utf-8",
                    },
                },
            }
        )


def test_source_spec_rejects_unknown_csv_encoding() -> None:
    with pytest.raises(ValueError, match="CSV encoding is unknown"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": "csv",
                    "location": "/tmp/employees.csv",
                    "options": {
                        "delimiter": ";",
                        "encoding": "not-a-real-encoding",
                    },
                },
            }
        )


def test_resolve_source_location_from_env(monkeypatch, employees_registry_path) -> None:
    monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", "/tmp/employees.csv")
    spec = load_source_spec_for_dataset("employees")
    assert resolve_source_location(spec) == "/tmp/employees.csv"


def test_resolve_source_location_raises_when_missing(monkeypatch, employees_registry_path) -> None:
    monkeypatch.delenv("EMPLOYEES_SOURCE_PATH", raising=False)
    spec = load_source_spec_for_dataset("employees")
    try:
        resolve_source_location(spec)
    except ValueError as exc:
        assert "source location is not configured" in str(exc)
        return
    raise AssertionError("ValueError was not raised")
