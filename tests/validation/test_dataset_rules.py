from connector.domain.transform.enrich import EnricherEngine
from connector.domain.transform.normalize import DslNormalizer
from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.transform.stages.stages import MapStage, NormalizeStage, EnrichStage, StagePipeline
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.domain.transform.mapping.dsl_mapper import DslMapper
from connector.domain.transform.dsl.loader import load_normalize_spec_for_dataset
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
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

    def find_user_by_target_id(self, _target_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None

    def find_org_by_ouid(self, _ouid: int):
        return {"_ouid": _ouid}


def make_employee(values: list[str | None], deps: ValidationDependencies):
    normalize_spec = load_normalize_spec_for_dataset("employees")
    registry = OperationRegistry()
    register_core_ops(registry)
    normalizer = DslNormalizer(
        normalize_spec,
        registry=registry,
        catalog=CATALOG,
        row_builder=NormalizedEmployeesRow,
    )
    enricher = EnricherEngine(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    mapper = DslMapper(catalog=CATALOG, dataset="employees")
    pipeline = StagePipeline(
        [
            MapStage(mapper, CATALOG),
            NormalizeStage(normalizer, CATALOG),
            EnrichStage(enricher, CATALOG),
        ]
    )
    validator = Validator(EmployeesValidationSpec(), deps, catalog=CATALOG)
    enriched = next(iter(pipeline.run([_collect(values, line_no=1)])))
    validated = validator.validate(enriched)
    entity = validated.row.row if validated.row else None
    result = validated.row.validation if validated.row else None
    return entity, result

def test_org_id_positive_int_validation():
    deps = ValidationDependencies()
    _employee, result = make_employee(
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
        deps,
    )
    assert result.valid

    _employee2, result2 = make_employee(
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
            "password=secret;org_id=-5;tab=TAB-200",
        ],
        deps,
    )
    assert not result2.valid
    assert any(e.code == "INVALID_INT" for e in result2.errors)
