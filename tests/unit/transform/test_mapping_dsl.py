from __future__ import annotations

import pytest

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.dsl.issues import DslLoadError
from connector.domain.transform_dsl.build_options import MapDslBuildOptions
from connector.domain.transform_dsl.specs import MappingSpec, SinkSpec
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.compilers.mapping import MapperDsl
from connector.domain.transform.mapping import MapperEngine


def test_employees_dsl_mapper_maps_record() -> None:
    catalog = build_catalog("employees", strict=True)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    record = SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "raw_id": "u-001",
            "full_name": "Doe, John M.",
            "login": "jdoe",
            "email_or_phone": "john.doe@example.com",
            "contacts": "+1-202-555-0100",
            "org": "Org:Engineering",
            "manager": "manager: 42",
            "flags": "disabled=false",
            "employment": "role=Engineer",
            "extra": "password=secret;org_id=77;tab=TAB-01",
        },
    )
    result = mapper.map(record)

    assert result.row is not None
    assert result.row["personnel_number"] == "u-001"
    assert result.row["last_name"] == "Doe"
    assert result.row["first_name"] == "John"
    assert result.row["middle_name"] == "M."
    assert result.row["email"] == "john.doe@example.com"
    assert result.row["phone"] == "+1-202-555-0100"
    assert result.row["manager_id"] == "42"
    assert result.row["is_logon_disable"] == "false"
    assert result.row["position"] == "Engineer"
    assert result.row["organization_id"] == "77"
    assert result.row["usr_org_tab_num"] == "TAB-01"
    assert result.row["avatar_id"] is None
    assert result.secret_candidates == {}
    assert result.row is not None
    assert result.row["password"] == "secret"
    assert result.meta.get("link_keys") is None
    assert result.errors == ()


def test_employees_dsl_mapper_missing_source_column() -> None:
    catalog = build_catalog("employees", strict=True)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    record = SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "raw_id": "u-001",
            # full_name отсутствует -> ошибка missing_source_column
            "login": "jdoe",
            "email_or_phone": "john.doe@example.com",
            "contacts": "+1-202-555-0100",
            "manager": "manager: 42",
            "flags": "disabled=false",
            "employment": "role=Engineer",
            "extra": "password=secret;org_id=77;tab=TAB-01",
        },
    )
    result = mapper.map(record)
    assert result.row is None
    assert any(err.code == "missing_source_column" for err in result.errors)


def test_mapper_dsl_fails_on_unknown_meta_operation() -> None:
    spec = MappingSpec.model_validate(
        {
            "dataset": "employees",
            "source_columns": ["a"],
            "mapping": {
                "rules": [
                    {
                        "target": "email",
                        "source": "a",
                        "ops": [{"op": "trim"}],
                    }
                ],
                "meta": [
                    {
                        "target": "trace",
                        "source": "a",
                        "ops": [{"op": "missing_op"}],
                    }
                ],
            },
        }
    )
    dsl = MapperDsl(options=MapDslBuildOptions(fail_on_unknown_ops=True))
    with pytest.raises(DslLoadError) as exc_info:
        dsl.compile(spec)
    assert exc_info.value.code == "DSL_OP_UNKNOWN"


def test_mapper_dsl_requires_sink_when_target_check_enabled() -> None:
    spec = MappingSpec.model_validate(
        {
            "dataset": "employees",
            "source_columns": ["a"],
            "mapping": {
                "rules": [
                    {
                        "target": "email",
                        "source": "a",
                        "ops": [{"op": "trim"}],
                    }
                ],
            },
        }
    )
    dsl = MapperDsl(options=MapDslBuildOptions(require_targets_exist_in_sink_spec=True))
    with pytest.raises(DslLoadError) as exc_info:
        dsl.compile(spec)
    assert exc_info.value.code == "MAP_DSL_COMPILE_INVALID"


def test_mapper_dsl_validates_target_presence_in_sink() -> None:
    spec = MappingSpec.model_validate(
        {
            "dataset": "employees",
            "source_columns": ["a"],
            "mapping": {
                "rules": [
                    {
                        "target": "missing_field",
                        "source": "a",
                        "ops": [{"op": "trim"}],
                    }
                ],
            },
        }
    )
    sink_spec = SinkSpec.model_validate(
        {
            "dataset": "employees",
            "sink": {
                "fields": [{"name": "email", "type": "string"}],
                "system_fields": [],
                "allow_extra": True,
            },
        }
    )
    dsl = MapperDsl(options=MapDslBuildOptions(require_targets_exist_in_sink_spec=True))
    with pytest.raises(DslLoadError) as exc_info:
        dsl.compile(spec, sink_spec=sink_spec)
    assert exc_info.value.code == "MAP_DSL_COMPILE_INVALID"
