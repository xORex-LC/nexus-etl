import logging

from connector.domain.models import CsvRow
from connector.domain.validation.pipeline import RowValidator
from connector.datasets.employees.source_mapper import EmployeesSourceMapper, to_employee_input
from connector.infra.artifacts.report_writer import createEmptyReport
from connector.datasets.employees.csv_record_adapter import EmployeesCsvRecordAdapter
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.usecases.mapping_usecase import MappingUseCase


def _make_row(values: list[str | None], line_no: int = 1) -> CsvRow:
    return CsvRow(
        file_line_no=line_no,
        data_line_no=line_no,
        values=values,
    )


def _run_mapping(rows: list[CsvRow]):
    usecase = MappingUseCase(report_items_limit=50, include_mapped_items=True)
    report = createEmptyReport(runId="run-1", command="mapping", configSources=[])
    mapping_spec = EmployeesMappingSpec()
    adapter = EmployeesCsvRecordAdapter()
    validator = RowValidator(EmployeesSourceMapper(mapping_spec), to_employee_input, mapping_spec.required_fields)
    record_source = [adapter.collect(row) for row in rows]
    exit_code = usecase.run(
        record_source=record_source,
        row_validator=validator,
        dataset="employees",
        logger=logging.getLogger("mapping-test"),
        run_id="run-1",
        report=report,
    )
    return exit_code, report


def test_mapping_reports_missing_match_key():
    row = _make_row(
        [
            "user@example.com",
            None,
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            None,
            "10",
            "Engineer",
            None,
            "TAB-100",
        ]
    )
    _exit_code, report = _run_mapping([row])

    dataset_summary = report.summary.by_dataset["employees"]
    assert dataset_summary["mapping_failed"] == 1
    assert report.items[0]["status"] == "mapping_failed"


def test_mapping_reports_secret_candidates():
    row = _make_row(
        [
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            None,
            "10",
            "Engineer",
            None,
            "TAB-100",
        ]
    )
    _exit_code, report = _run_mapping([row])

    assert report.items[0]["status"] == "mapped"
    assert report.items[0]["secret_candidate_fields"] == ["password"]


def test_mapping_reports_mapped_ok():
    row = _make_row(
        [
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            None,
            "10",
            "Engineer",
            None,
            "TAB-100",
        ]
    )
    _exit_code, report = _run_mapping([row])

    dataset_summary = report.summary.by_dataset["employees"]
    assert dataset_summary["mapped_ok"] == 1
    assert dataset_summary["mapping_failed"] == 0
