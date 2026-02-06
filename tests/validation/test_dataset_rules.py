from connector.domain.transform.enrich import EnricherEngine, EnrichDslBuildOptions
from connector.domain.transform.normalize import NormalizerDsl, NormalizerEngine
from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.transform.stages.stages import MapStage, NormalizeStage, EnrichStage, StagePipeline
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.dsl.loader import load_mapping_spec_for_dataset, load_normalize_spec_for_dataset
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.datasets.employees.transform.validation_spec import EmployeesValidationSpec
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)
SOURCE_COLUMNS = load_mapping_spec_for_dataset("employees").source_columns


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
    dictionaries = None
    secret_store = None

    class _CacheRepo:
        def find(self, dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
            _ = (dataset, filters, include_deleted, mode)
            return []

        def find_one(
            self,
            dataset: str,
            filters: dict[str, object],
            *,
            include_deleted: bool = False,
            mode: str = "exact",
        ):
            _ = (dataset, filters, include_deleted, mode)
            return None

    cache_repo = _CacheRepo()


def make_employee(values: list[str | None], deps: ValidationDependencies):
    normalize_spec = load_normalize_spec_for_dataset("employees")
    registry = OperationRegistry()
    register_core_ops(registry)
    normalizer = NormalizerEngine(
        normalize_spec,
        catalog=CATALOG,
        dsl=NormalizerDsl(registry=registry),
        row_builder=NormalizedEmployeesRow,
    )
    enricher = EnricherEngine(
        spec=EmployeesEnricherSpec(),
        deps=_DummyEnrichDeps(),
        secret_store=None,
        dataset="employees",
        catalog=CATALOG,
        registry=registry,
        options=EnrichDslBuildOptions(require_match_key=True),
    )
    mapper = MapperEngine.from_dataset(catalog=CATALOG, dataset="employees")
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
