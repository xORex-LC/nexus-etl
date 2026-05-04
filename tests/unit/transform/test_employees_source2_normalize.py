from __future__ import annotations

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.normalize import NormalizerEngine


def _source2_record_1() -> SourceRecord:
    return SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "Таб.№": "4001182",
            "Пользователи": "Гапоненко Михаил Викторович",
            "Орг. единица уровня 1": "Подразделения при администрации",
            "Орг. единица уровня 2": "Служба информационно-управляющих систем",
            "Орг. единица уровня 3": "Отдел администрирования, сопровождения и развития локальных ИУС",
            "Орг. единица уровня 4": "",
            "Орг. единица уровня 5": "",
            "Организационная единица": "Отдел администрирования, сопровождения и",
            "Штатная должность": "Начальник отдела",
            "Поступл.": "",
            "Contract Number": "014т/18",
            "Догвр:нач.": "03.02.2018",
            "Название руководящей должности": "Начальник отдела",
            "ДатаРожд": "04.05.1985",
            "Пол": "мужской",
        },
    )


def _source2_record_2() -> SourceRecord:
    return SourceRecord(
        line_no=2,
        record_id="line:2",
        values={
            "Таб.№": "4001017",
            "Пользователи": "Самохвалов Семен Анатольевич",
            "Орг. единица уровня 1": "Подразделения при администрации",
            "Орг. единица уровня 2": "Служба корпоративной защиты",
            "Орг. единица уровня 3": "Отдел информационной безопасности",
            "Орг. единица уровня 4": "",
            "Орг. единица уровня 5": "",
            "Организационная единица": "Отдел информационной безопасности",
            "Штатная должность": "Начальник отдела",
            "Поступл.": "",
            "Contract Number": "039т/14",
            "Догвр:нач.": "06.10.2014",
            "Название руководящей должности": "Начальник отдела",
            "ДатаРожд": "12.01.1985",
            "Пол": "мужской",
        },
    )


def test_source2_normalize_selects_last_non_empty_organization_unit(employees_registry_path) -> None:
    catalog = build_catalog("employees", strict=False)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    normalizer = NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)

    mapped = mapper.map(_source2_record_1())
    result = normalizer.normalize(mapped)

    assert result.row is not None
    assert result.row["organization_id"] == "Отдел администрирования, сопровождения и"
    assert result.row["is_logon_disable"] is False
    assert result.row["last_name"] == "Гапоненко"
    assert result.row["first_name"] == "Михаил"
    assert result.row["middle_name"] == "Викторович"
    assert result.row["position"] == "Начальник Отдела"
    assert result.errors == ()
    assert any(w.code == "SINK_TYPE_INVALID" and w.field == "organization_id" for w in result.warnings)


def test_source2_normalize_uses_declared_last_non_empty_rule_for_other_rows(employees_registry_path) -> None:
    catalog = build_catalog("employees", strict=False)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    normalizer = NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)

    mapped = mapper.map(_source2_record_2())
    result = normalizer.normalize(mapped)

    assert result.row is not None
    assert result.row["organization_id"] == "Отдел информационной безопасности"
    assert result.row["is_logon_disable"] is False
    assert result.errors == ()
    assert any(w.code == "SINK_TYPE_INVALID" and w.field == "organization_id" for w in result.warnings)
