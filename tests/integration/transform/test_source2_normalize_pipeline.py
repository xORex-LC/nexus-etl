from __future__ import annotations

from pathlib import Path

from connector.datasets import registry as dataset_registry_module
from connector.datasets.registry import get_spec
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.dsl.loader import configure_registry_path
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.normalize import NormalizerEngine
from tests.integration.secrets._temp_registry import build_temp_employees_registry_with_temp_dictionaries


HEADER = ";".join(
    [
        "Таб.№",
        "Пользователи",
        "Орг. единица уровня 1",
        "Орг. единица уровня 2",
        "Орг. единица уровня 3",
        "Орг. единица уровня 4",
        "Орг. единица уровня 5",
        "Организационная единица",
        "Штатная должность",
        "Поступл.",
        "Contract Number",
        "Догвр:нач.",
        "Название руководящей должности",
        "ДатаРожд",
        "Пол",
    ]
)


def _write_source2_csv(path: Path) -> None:
    rows = [
        [
            "4001182",
            "гапоненко михаил Викторович",
            "Подразделения при администрации",
            "Служба информационно-управляющих систем",
            "Отдел администрирования, сопровождения и развития локальных ИУС",
            "",
            "",
            "Отдел администрирования, сопровождения и развития локальных ИУС",
            "Начальник отдела",
            "",
            "014т/18",
            "03.02.2018",
            "Начальник отдела",
            "04.05.1985",
            "мужской",
        ],
        [
            "4001017",
            "Самохвалов Семен Анатольевич",
            "Подразделения при администрации",
            "Служба корпоративной защиты",
            "Отдел информационной безопасности",
            "",
            "",
            "Отдел информационной безопасности",
            "Начальник отдела",
            "",
            "039т/14",
            "06.10.2014",
            "Начальник отдела",
            "12.01.1985",
            "мужской",
        ],
    ]
    content = "\n".join([HEADER, *(";".join(row) for row in rows)])
    path.write_text(content, encoding="utf-8")


def test_source2_real_csv_map_and_normalize_pipeline(monkeypatch, tmp_path: Path) -> None:
    registry_path, _ = build_temp_employees_registry_with_temp_dictionaries(tmp_path)
    csv_path = tmp_path / "source2.csv"
    _write_source2_csv(csv_path)

    monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", str(csv_path))
    configure_registry_path(registry_path)
    dataset_registry_module._registry = None
    try:
        dataset_spec = get_spec("employees")
        catalog = build_catalog("employees", strict=False)
        mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
        normalizer = NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)

        normalized_results: list[TransformResult] = []
        for record in dataset_spec.build_record_source():
            mapped = mapper.map(record)
            normalized_results.append(normalizer.normalize(mapped))

        rows = [result.row for result in iter_ok(normalized_results)]
    finally:
        configure_registry_path(None)
        dataset_registry_module._registry = None

    assert len(rows) == 2
    assert rows[0]["organization_id"] == "Отдел администрирования, сопровождения и развития локальных ИУС"
    assert rows[1]["organization_id"] == "Отдел информационной безопасности"
    assert rows[0]["is_logon_disable"] is False
    assert rows[1]["is_logon_disable"] is False
    assert rows[0]["last_name"] == "Гапоненко"
    assert rows[1]["last_name"] == "Самохвалов"
