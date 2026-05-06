from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.runtime_paths import RuntimePathOverrides
from connector.domain.dsl.loader import configure_runtime_paths
from connector.domain.transform_dsl import load_source_spec_for_dataset, resolve_source_location
from connector.domain.transform_dsl.specs import SourceSpec


def test_load_source_spec_for_dataset(employees_registry_path) -> None:
    spec = load_source_spec_for_dataset("employees")
    assert spec.dataset == "employees"
    assert spec.source.type == "file"
    assert spec.source.format == "csv"
    assert spec.source.location == "source_employees_example.csv"
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


def test_resolve_source_location_uses_runtime_source_data_root(
    tmp_path: Path,
    employees_registry_path,
) -> None:
    configure_runtime_paths(
        RuntimePathOverrides(
            source_data_root=tmp_path / "custom-sources",
        )
    )
    spec = load_source_spec_for_dataset("employees")
    try:
        assert resolve_source_location(spec) == str(
            (tmp_path / "custom-sources" / "source_employees_example.csv").resolve()
        )
    finally:
        configure_runtime_paths(None)


def test_source_spec_requires_location_for_file_sources() -> None:
    with pytest.raises(ValueError, match="source.location must be configured"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": "csv",
                },
            }
        )
