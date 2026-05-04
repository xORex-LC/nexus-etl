from __future__ import annotations

from pathlib import Path

from connector.datasets.registry import get_spec
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.normalize import NormalizerEngine


def test_source2_real_csv_map_and_normalize_pipeline(monkeypatch, employees_registry_path) -> None:
    csv_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "sources"
        / "source_employees_example_1.csv"
    )
    monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", str(csv_path))

    dataset_spec = get_spec("employees")
    catalog = build_catalog("employees", strict=False)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    normalizer = NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)

    normalized_results: list[TransformResult] = []
    for record in dataset_spec.build_record_source():
        mapped = mapper.map(record)
        normalized_results.append(normalizer.normalize(mapped))

    rows = [result.row for result in iter_ok(normalized_results)]

    assert len(rows) == 2
    assert rows[0]["organization_id"] == "Отдел администрирования, сопровождения и"
    assert rows[1]["organization_id"] == "Отдел информационной безопасности"
    assert rows[0]["is_logon_disable"] is False
    assert rows[1]["is_logon_disable"] is False
    assert rows[0]["last_name"] == "Гапоненко"
    assert rows[1]["last_name"] == "Самохвалов"
