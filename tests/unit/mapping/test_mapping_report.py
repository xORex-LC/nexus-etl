import logging
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform_dsl import load_mapping_spec_for_dataset
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import ReportSink
from connector.usecases.mapping_usecase import MappingUseCase
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.stages.stages import MapStage, PipelineOrchestrator

CATALOG = build_catalog("employees", strict=True)
SOURCE_COLUMNS = load_mapping_spec_for_dataset("employees").source_columns


def _make_record(values: dict[str, str | None], line_no: int = 1) -> SourceRecord:
    mapped = {column: "" for column in SOURCE_COLUMNS}
    mapped.update(values)
    return SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=mapped,
    )

def _run_mapping(records: list[SourceRecord]):
    usecase = MappingUseCase(report_items_limit=50, include_mapped_items=True)
    context = InMemoryReportContext(run_id="run-1", command="mapping")
    sink = ReportSink(context)
    map_stage = MapStage(MapperEngine.from_dataset(catalog=CATALOG, dataset="employees"), CATALOG)
    pipeline = PipelineOrchestrator([map_stage])
    row_source = records
    result = usecase.run(
        row_source=row_source,
        pipeline=pipeline,
        dataset="employees",
        logger=logging.getLogger("mapping-test"),
        run_id="run-1",
        report_sink=sink,
        report_policy=ReportPolicy.standard(),
        catalog=CATALOG,
    )
    return result, ReportAssembler(context=context).assemble()


def test_mapping_reports_missing_match_key():
    row = _make_record(
        {
            "Таб.№": "100",
            "Пользователи": "",
            "Организационная единица": "Org 10",
            "Штатная должность": "Engineer",
            "Contract Number": "+111111",
        }
    )
    _result, report = _run_mapping([row])

    assert report.summary.rows_blocked == 0
    assert report.summary.rows_passed == 1
    assert report.items[0].status == "OK"


def test_mapping_reports_secret_candidates():
    row = _make_record(
        {
            "Таб.№": "100",
            "Пользователи": "Doe John M",
            "Организационная единица": "Org 10",
            "Штатная должность": "Engineer",
            "Contract Number": "+111111",
        }
    )
    _result, report = _run_mapping([row])

    assert report.items[0].status == "OK"
    assert report.items[0].meta["secret_candidate_fields"] == []


def test_mapping_reports_mapped_ok():
    row = _make_record(
        {
            "Таб.№": "100",
            "Пользователи": "Doe John M",
            "Организационная единица": "Org 10",
            "Штатная должность": "Engineer",
            "Contract Number": "+111111",
        }
    )
    _result, report = _run_mapping([row])

    assert report.summary.rows_passed == 1
    assert report.summary.rows_blocked == 0
