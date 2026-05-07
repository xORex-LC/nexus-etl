from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import RowRef
from connector.domain.ports.transform.sources import SourceMapper
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.diagnostics import build_catalog
from connector.domain.transform.mapping import MapperEngine


def test_employees_source_mapper_builds_secrets(employees_registry_path):
    catalog = build_catalog("employees", strict=True)
    record = SourceRecord(
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
    result = MapperEngine.from_dataset(catalog=catalog, dataset="employees").map(record)

    assert result.errors == ()
    assert result.match_key is None
    assert result.secret_candidates == {}
    assert result.row is not None
    assert result.row.get("password") is None
    assert result.row["email"] is None
    assert result.row_ref is None


def test_employees_source_mapper_does_not_add_match_key_errors(employees_registry_path):
    catalog = build_catalog("employees", strict=True)
    record = SourceRecord(
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
    result = MapperEngine.from_dataset(catalog=catalog, dataset="employees").map(record)

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" not in codes
    assert result.match_key is None


def test_no_secrets_source_mapper_keeps_secret_candidates_empty():
    @dataclass
    class CarRowPublic:
        vin: str

    class CarsSourceMapper(SourceMapper[CarRowPublic]):
        def map(self, record: SourceRecord) -> TransformResult[CarRowPublic]:
            row_ref = RowRef(
                line_no=record.line_no,
                row_id=record.record_id,
                identity_primary=None,
                identity_value=None,
            )
            return TransformResult(
                record=record,
                row=CarRowPublic(vin="VIN-1"),
                row_ref=row_ref,
                match_key=None,
            )

    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = CarsSourceMapper().map(record)
    assert result.secret_candidates == {}
