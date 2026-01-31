import logging

from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.extract.source_mapper import EmployeesSourceMapper
from connector.infra.artifacts.report_writer import createEmptyReport
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec
from connector.usecases.mapping_usecase import MappingUseCase
from connector.datasets.employees.transform.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.extract.source_mapper import SOURCE_COLUMNS


def _make_record(values: list[str | None], line_no: int = 1) -> SourceRecord:
    mapped = dict(zip(SOURCE_COLUMNS, values))
    return SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=mapped,
    )

class _DummyEnrichDeps:
    identity_lookup = None

    def find_user_by_target_id(self, _target_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None

    def find_org_by_ouid(self, _ouid: int):
        return {"_ouid": _ouid}


def _run_mapping(records: list[SourceRecord]):
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
    row_source = records
    exit_code = usecase.run(
        row_source=row_source,
        transformer=transformer,
        dataset="employees",
        logger=logging.getLogger("mapping-test"),
        run_id="run-1",
        report=report,
    )
    return exit_code, report


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
    _exit_code, report = _run_mapping([row])

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
    _exit_code, report = _run_mapping([row])

    assert report.items[0].status == "OK"
    assert report.items[0].meta["secret_candidate_fields"] == ["password"]


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
    _exit_code, report = _run_mapping([row])

    assert report.summary.rows_passed == 1
    assert report.summary.rows_blocked == 0
