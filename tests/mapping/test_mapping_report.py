import logging

from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.infra.artifacts.report_writer import createEmptyReport
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.usecases.mapping_usecase import MappingUseCase
from connector.datasets.employees.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.record_sources import SOURCE_COLUMNS


def _make_row(values: list[str | None], line_no: int = 1) -> TransformResult[None]:
    mapped = dict(zip(SOURCE_COLUMNS, values))
    record = SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=mapped,
    )
    return TransformResult(
        record=record,
        row=None,
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

class _DummyEnrichDeps:
    identity_lookup = None

    def find_user_by_id(self, _resource_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None


def _run_mapping(rows: list[TransformResult[None]]):
    usecase = MappingUseCase(report_items_limit=50, include_mapped_items=True)
    report = createEmptyReport(runId="run-1", command="mapping", configSources=[])
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(
        EmployeesSourceMapper(mapping_spec),
        normalizer,
        enricher,
    )
    record_source = rows
    exit_code = usecase.run(
        record_source=record_source,
        transformer=transformer,
        dataset="employees",
        logger=logging.getLogger("mapping-test"),
        run_id="run-1",
        report=report,
    )
    return exit_code, report


def test_mapping_reports_missing_match_key():
    row = _make_row(
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
    _exit_code, report = _run_mapping([row])

    dataset_summary = report.summary.by_dataset["employees"]
    assert dataset_summary["mapping_failed"] == 1
    assert report.items[0]["status"] == "mapping_failed"


def test_mapping_reports_secret_candidates():
    row = _make_row(
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
    _exit_code, report = _run_mapping([row])

    assert report.items[0]["status"] == "mapped"
    assert report.items[0]["secret_candidate_fields"] == ["password"]


def test_mapping_reports_mapped_ok():
    row = _make_row(
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
    _exit_code, report = _run_mapping([row])

    dataset_summary = report.summary.by_dataset["employees"]
    assert dataset_summary["mapped_ok"] == 1
    assert dataset_summary["mapping_failed"] == 0
