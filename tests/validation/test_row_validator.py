from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.stages.stages import MapStage, NormalizeStage, EnrichStage, StagePipeline
from connector.datasets.employees.extract.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.transform.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.extract.source_mapper import SOURCE_COLUMNS
from connector.datasets.employees.transform.validation_spec import EmployeesValidationSpec
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)


def _collect(values: list[str | None], line_no: int = 1) -> TransformResult[None]:
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
    secret_store = None

    def find_user_by_target_id(self, target_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, tab_num: str):
        return None

    def find_org_by_ouid(self, _ouid: int):
        return {"_ouid": _ouid}

def _build_pipeline() -> StagePipeline:
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec(), catalog=CATALOG)
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    mapper = EmployeesSourceMapper(mapping_spec, catalog=CATALOG)
    return StagePipeline(
        [
            MapStage(mapper, CATALOG),
            NormalizeStage(normalizer, CATALOG),
            EnrichStage(enricher, CATALOG),
        ]
    )

def test_row_validator_parses_valid_row():
    collected = _collect(
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
            "password=secret;org_id=20;tab=TAB-100",
        ],
        line_no=1,
    )
    pipeline = _build_pipeline()
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies(), catalog=CATALOG)
    enriched = next(iter(pipeline.run([collected])))
    validated = validator.validate(enriched)
    entity = validated.row.row if validated.row else None
    result = validated.row.validation if validated.row else None

    assert result.valid
    assert entity.email == "user@example.com"
    assert entity.organization_id == 20
    assert result.match_key == "Doe|John|M|100"

def test_row_validator_reports_missing_required():
    collected = _collect([None for _ in range(10)], line_no=1)
    pipeline = _build_pipeline()
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies(), catalog=CATALOG)
    enriched = next(iter(pipeline.run([collected])))
    validated = validator.validate(enriched)
    result = validated.row.validation if validated.row else None

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "MATCH_KEY_MISSING" in codes

def test_row_validator_invalid_email():
    collected = _collect(
        [
            "100",
            "Doe John M",
            "jdoe",
            "john.doe@example",
            "+111111",
            "Org=Engineering",
            "",
            "disabled=false",
            "role=Engineer",
            "password=secret;org_id=20;tab=TAB-100",
        ],
        line_no=1,
    )
    pipeline = _build_pipeline()
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies(), catalog=CATALOG)
    enriched = next(iter(pipeline.run([collected])))
    validated = validator.validate(enriched)
    result = validated.row.validation if validated.row else None

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "INVALID_EMAIL" in codes


def test_row_validator_produces_row_ref_even_with_errors():
    collected = _collect([None for _ in range(10)], line_no=5)
    pipeline = _build_pipeline()
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies(), catalog=CATALOG)
    enriched = next(iter(pipeline.run([collected])))
    validated = validator.validate(enriched)
    result = validated.row.validation if validated.row else None

    assert result.row_ref is not None
    assert result.row_ref.row_id == "line:5"
    assert result.row_ref.identity_primary == "match_key"
