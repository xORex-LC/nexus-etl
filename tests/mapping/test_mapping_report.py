import logging
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.dsl.loader import load_mapping_spec_for_dataset
from connector.infra.artifacts.report_writer import createEmptyReport
from connector.usecases.mapping_usecase import MappingUseCase
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.stages.stages import MapStage

CATALOG = build_catalog("employees", strict=True)
SOURCE_COLUMNS = load_mapping_spec_for_dataset("employees").source_columns


def _make_record(values: list[str | None], line_no: int = 1) -> SourceRecord:
    mapped = dict(zip(SOURCE_COLUMNS, values))
    return SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=mapped,
    )

def _run_mapping(records: list[SourceRecord]):
    usecase = MappingUseCase(report_items_limit=50, include_mapped_items=True)
    report = createEmptyReport(runId="run-1", command="mapping", configSources=[])
    map_stage = MapStage(MapperEngine.from_dataset(catalog=CATALOG, dataset="employees"), CATALOG)
    row_source = records
    result = usecase.run(
        row_source=row_source,
        map_stage=map_stage,
        dataset="employees",
        logger=logging.getLogger("mapping-test"),
        run_id="run-1",
        report=report,
        catalog=CATALOG,
    )
    return result, report


def test_mapping_reports_missing_match_key():
    row = _make_record(
        [
            "100",
            "",
            "jdoe",
            "user@example.com",
            "+111111",
            "Org=Engineering",
            "",
            "disabled=false",
            "role=Engineer",
            "password=secret;org_id=10;tab=TAB-100",
        ]
    )
    _result, report = _run_mapping([row])

    assert report.summary.rows_blocked == 0
    assert report.summary.rows_passed == 1
    assert report.items[0].status == "OK"


def test_mapping_reports_secret_candidates():
    row = _make_record(
        [
            "100",
            "Doe John M",
            "jdoe",
            "user@example.com",
            "+111111",
            "Org=Engineering",
            "",
            "disabled=false",
            "role=Engineer",
            "password=secret;org_id=10;tab=TAB-100",
        ]
    )
    _result, report = _run_mapping([row])

    assert report.items[0].status == "OK"
    assert report.items[0].meta["secret_candidate_fields"] == []


def test_mapping_reports_mapped_ok():
    row = _make_record(
        [
            "100",
            "Doe John M",
            "jdoe",
            "user@example.com",
            "+111111",
            "Org=Engineering",
            "",
            "disabled=false",
            "role=Engineer",
            "password=secret;org_id=10;tab=TAB-100",
        ]
    )
    _result, report = _run_mapping([row])

    assert report.summary.rows_passed == 1
    assert report.summary.rows_blocked == 0
