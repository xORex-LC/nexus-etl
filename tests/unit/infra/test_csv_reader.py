from __future__ import annotations

from connector.infra.sources.csv_reader import CsvRecordSource


def test_csv_record_source_uses_declared_delimiter_with_header(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text(
        "raw_id;full_name;login\n"
        "001;Doe John;jdoe\n",
        encoding="utf-8",
    )

    records = list(
        CsvRecordSource(
            str(path),
            has_header=True,
            delimiter=";",
            encoding="utf-8",
        )
    )

    assert len(records) == 1
    assert records[0].line_no == 2
    assert records[0].values == {
        "raw_id": "001",
        "full_name": "Doe John",
        "login": "jdoe",
    }


def test_csv_record_source_uses_declared_delimiter_without_header(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("001;Doe John;jdoe\n", encoding="utf-8")

    records = list(
        CsvRecordSource(
            str(path),
            has_header=False,
            delimiter=";",
            encoding="utf-8",
        )
    )

    assert len(records) == 1
    assert records[0].line_no == 1
    assert records[0].values == {
        "col_0": "001",
        "col_1": "Doe John",
        "col_2": "jdoe",
    }
