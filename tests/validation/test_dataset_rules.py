from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.source_mapper import SOURCE_COLUMNS
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

class DummyOrgLookup:
    def __init__(self, existing_ids: set[int]):
        self.existing_ids = existing_ids

    def get_by_id(self, entity: str, value: int):
        if entity not in ("organizations", "orgs"):
            return None
        return {"_ouid": value} if value in self.existing_ids else None

    def match(self, identity, include_deleted: bool):
        raise NotImplementedError


class _DummyEnrichDeps:
    identity_lookup = None

    def find_user_by_id(self, _resource_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None


def make_employee(values: list[str | None], deps: ValidationDependencies):
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    transformer = TransformPipeline(EmployeesSourceMapper(mapping_spec), normalizer, enricher)
    validator = Validator(EmployeesValidationSpec(), deps)
    validated = validator.validate(transformer.enrich(_collect(values, line_no=1)))
    entity = validated.row.row if validated.row else None
    result = validated.row.validation if validated.row else None
    return entity, result

def test_org_exists_rule_checks_lookup():
    deps = ValidationDependencies(org_lookup=DummyOrgLookup(existing_ids={20}))
    employee, result = make_employee(
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
            "password=secret;org_id=20;tab=TAB-100",  # exists
        ],
        deps,
    )
    assert result.valid

    employee2, result2 = make_employee(
        [
            "200",
            "Doe John M",
            "jdoe2",
            "user2@example.com",
            "+222222",
            "Org=Engineering",
            "",
            "disabled=false",
            "role=Engineer",
            "password=secret;org_id=999;tab=TAB-200",  # missing
        ],
        deps,
    )
    assert not result2.valid
    assert any(e.code == "ORG_NOT_FOUND" for e in result2.errors)
