import pytest

from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.pipeline import TransformPipeline
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.record_sources import SOURCE_COLUMNS
from connector.datasets.employees.validation_spec import EmployeesValidationSpec


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

    def find_user_by_id(self, resource_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, tab_num: str):
        return None

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
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(EmployeesSourceMapper(mapping_spec), normalizer, enricher)
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies())
    validated = validator.validate(transformer.enrich(collected))
    entity = validated.row.row if validated.row else None
    result = validated.row.validation if validated.row else None

    assert result.valid
    assert entity.email == "user@example.com"
    assert entity.organization_id == 20
    assert result.match_key == "Doe|John|M|100"

def test_row_validator_reports_missing_required():
    collected = _collect([None for _ in range(10)], line_no=1)
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(EmployeesSourceMapper(mapping_spec), normalizer, enricher)
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies())
    validated = validator.validate(transformer.enrich(collected))
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
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(EmployeesSourceMapper(mapping_spec), normalizer, enricher)
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies())
    validated = validator.validate(transformer.enrich(collected))
    result = validated.row.validation if validated.row else None

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "INVALID_EMAIL" in codes


def test_row_validator_produces_row_ref_even_with_errors():
    collected = _collect([None for _ in range(10)], line_no=5)
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(EmployeesSourceMapper(mapping_spec), normalizer, enricher)
    validator = Validator(EmployeesValidationSpec(), ValidationDependencies())
    validated = validator.validate(transformer.enrich(collected))
    result = validated.row.validation if validated.row else None

    assert result.row_ref is not None
    assert result.row_ref.row_id == "line:5"
    assert result.row_ref.identity_primary == "match_key"
