from __future__ import annotations

import pytest

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.dsl.issues import DslLoadError
from connector.domain.transform_dsl.build_options import MapDslBuildOptions
from connector.domain.transform_dsl.specs import MappingSpec, SinkSpec
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.compilers.mapping import MapperDsl
from connector.domain.transform.mapping import MapperEngine
from tests.support.dataset_artifacts import build_mapper, controlled_source_record


def test_mapper_maps_controlled_record() -> None:
    """Механика маппинга на контролируемой спеке (copy + multi-source list),
    отвязано от живого employees YAML — правка датасета не ломает этот тест."""
    mapper = build_mapper()
    result = mapper.map(
        controlled_source_record(
            emp_id="4001182",
            last_raw="Гапоненко",
            first_raw="Михаил",
            unit_l1="Подразделения при администрации",
            unit_l2="Служба информационно-управляющих систем",
            unit_l3="Отдел администрирования",
            phone_raw="014т/18",
            active_flag="false",
        )
    )

    assert result.errors == ()
    assert result.row is not None
    assert result.row["code"] == "4001182"
    assert result.row["last_name"] == "Гапоненко"
    assert result.row["first_name"] == "Михаил"
    # multi-source list aggregation — именно эта механика ломалась при правке состава колонок
    assert result.row["org_path"] == [
        "Подразделения при администрации",
        "Служба информационно-управляющих систем",
        "Отдел администрирования",
    ]
    assert result.row["phone"] == "014т/18"
    assert result.row["is_active"] == "false"
    assert result.secret_candidates == {}
    assert result.meta.get("link_keys") is None


def test_employees_dsl_mapper_missing_source_column(employees_registry_path) -> None:
    catalog = build_catalog("employees", strict=True)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    record = SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "Таб.№": "4001182",
            # Пользователи отсутствует -> ошибка missing_source_column
            "Орг. единица уровня 1": "Подразделения при администрации",
            "Организационная единица": "Отдел администрирования, сопровождения и",
            "Штатная должность": "Начальник отдела",
            "Contract Number": "014т/18",
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
