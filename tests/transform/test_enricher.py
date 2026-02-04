from __future__ import annotations

from dataclasses import dataclass

from connector.domain.transform.enricher import (
    CandidateValue,
    ConflictResolver,
    Enricher,
    EnricherSpec,
    EnrichmentOperation,
    EnrichOperationType,
    KeyRegistry,
    RunWhenErrors,
    StrictnessPolicy,
    EnrichOutcome,
)
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)


@dataclass
class _DummyEnrichDeps:
    identity_lookup = None

    def find_user_by_target_id(self, _target_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None

    def find_org_by_ouid(self, _ouid: int):
        return {"_ouid": _ouid}


class _ConflictingTabDeps(_DummyEnrichDeps):
    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return {"match_key": "OTHER"}


class _DummySecretStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], str | None]] = []

    def put_many(self, dataset: str, match_key: str, secrets: dict[str, str], run_id: str | None) -> None:
        self.calls.append((dataset, match_key, secrets, run_id))


def _build_result(
    row: NormalizedEmployeesRow, secret_candidates: dict[str, str] | None = None
) -> TransformResult[NormalizedEmployeesRow]:
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    return TransformResult(
        record=record,
        row=row,
        row_ref=None,
        match_key=None,
        secret_candidates=secret_candidates or {},
        errors=[],
        warnings=[],
    )


def test_enricher_builds_match_key_and_generates_values():
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num=None,
        target_id=None,
    )
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    result = enricher.enrich(_build_result(row))

    assert result.errors == ()
    assert result.match_key is not None
    assert result.match_key.value == "Doe|John|M|100"
    assert result.row.target_id is not None
    assert result.row.usr_org_tab_num is not None
    assert result.secret_candidates.get("password")
    summary = result.meta.get("enrich_summary")
    assert summary is not None
    assert summary["operations_total"] == 4
    assert summary["outcomes"].get("APPLIED") == 4


def test_enricher_reports_missing_match_key():
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name=None,
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id="RID-1",
    )
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    result = enricher.enrich(_build_result(row))

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" in codes
    assert result.match_key is None


def test_enricher_runs_only_allowed_ops_on_error():
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num=None,
        target_id=None,
    )
    result = _build_result(row).with_added_errors(
        [
            DiagnosticItem(
                stage=DiagnosticStage.MAP,
                code="DUMMY_ERROR",
                field=None,
                message="upstream error",
            )
        ]
    )
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    enriched = enricher.enrich(result)

    assert enriched.match_key is not None
    assert enriched.row.target_id is None
    assert enriched.row.usr_org_tab_num is None
    summary = enriched.meta.get("enrich_summary")
    assert summary is not None
    assert summary["operations_total"] == 1


def test_enricher_writes_secrets_to_store():
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id="RID-1",
    )
    secret_store = _DummySecretStore()
    enricher = Enricher(
        EmployeesEnricherSpec(),
        _DummyEnrichDeps(),
        secret_store,
        "employees",
        catalog=CATALOG,
        run_id="run-1",
    )
    result = enricher.enrich(_build_result(row, {"password": "secret"}))

    assert result.errors == ()
    assert secret_store.calls
    dataset, match_key, secrets, run_id = secret_store.calls[0]
    assert dataset == "employees"
    assert match_key == "Doe|John|M|100"
    assert secrets == {"password": "secret"}
    assert run_id == "run-1"


def test_enricher_reports_usr_org_tab_conflict():
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num=None,
        target_id=None,
    )
    enricher = Enricher(EmployeesEnricherSpec(), _ConflictingTabDeps(), None, "employees", catalog=CATALOG)
    result = enricher.enrich(_build_result(row))

    codes = {issue.code for issue in result.errors}
    assert "USR_ORG_TAB_CONFLICT" in codes


def test_conflict_resolver_prefers_higher_priority():
    resolver = ConflictResolver()
    low = CandidateValue(field="field", value="low", source="computed", priority=1, confidence=0.5)
    high = CandidateValue(field="field", value="high", source="sink_cache", priority=10, confidence=0.1)

    decision = resolver.decide([low, high])

    assert decision.selected is not None
    assert decision.selected.value == "high"


def test_enricher_rejects_multi_target_operation():
    @dataclass
    class _Row:
        a: str | None = None
        b: str | None = None

    def _compute(result, deps):
        _ = deps
        return {"a": "value"}

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="multi",
                op_type=EnrichOperationType.COMPUTE,
                targets=("a", "b"),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                compute=_compute,
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = Enricher(spec, _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = TransformResult(
        record=record,
        row=_Row(),
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

    enriched = enricher.enrich(result)

    codes = {issue.code for issue in enriched.errors}
    assert "ENRICH_MULTI_TARGET_UNSUPPORTED" in codes


def test_enricher_defaults_priority_by_source():
    @dataclass
    class _Row:
        field: str | None = None

    class _Provider:
        name = "provider"

        def fetch(self, ctx, result, deps, key_values):
            _ = (ctx, result, deps, key_values)
            return [
                CandidateValue(field="field", value="low", source="low", priority=None),
                CandidateValue(field="field", value="high", source="high", priority=None),
            ]

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="lookup",
                op_type=EnrichOperationType.LOOKUP,
                targets=("field",),
                providers=(_Provider(),),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.WARNED),
            ),
        ),
        key_registry=KeyRegistry(builders={}),
        source_priorities={"low": 1, "high": 10},
    )
    enricher = Enricher(spec, _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = TransformResult(
        record=record,
        row=_Row(),
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

    enriched = enricher.enrich(result)

    assert enriched.row.field == "high"


def test_enricher_warns_on_candidate_field_mismatch():
    @dataclass
    class _Row:
        field: str | None = None

    class _Provider:
        name = "provider"

        def fetch(self, ctx, result, deps, key_values):
            _ = (ctx, result, deps, key_values)
            return [
                CandidateValue(field="other", value="x", source="source", priority=1),
            ]

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="lookup",
                op_type=EnrichOperationType.LOOKUP,
                targets=("field",),
                providers=(_Provider(),),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.WARNED),
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = Enricher(spec, _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = TransformResult(
        record=record,
        row=_Row(),
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

    enriched = enricher.enrich(result)
    codes = {issue.code for issue in enriched.warnings}
    assert "ENRICH_TARGET_MISMATCH" in codes


def test_enricher_stop_on_failed_prevents_followup_ops():
    @dataclass
    class _Row:
        field: str | None = None

    def _compute(result, deps):
        _ = (result, deps)
        raise Exception("boom")

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="compute_fail",
                op_type=EnrichOperationType.COMPUTE,
                targets=("field",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                compute=_compute,
            ),
            EnrichmentOperation(
                name="should_not_run",
                op_type=EnrichOperationType.GENERATE,
                targets=("field",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.WARNED),
                generator=lambda _r, _d: "value",
            ),
        ),
        key_registry=KeyRegistry(builders={}),
        stop_on_failed=True,
    )
    enricher = Enricher(spec, _DummyEnrichDeps(), None, "employees", catalog=CATALOG)
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = TransformResult(
        record=record,
        row=_Row(),
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

    enriched = enricher.enrich(result)

    codes = {issue.code for issue in enriched.errors}
    assert "ENRICH_PROVIDER_ERROR" in codes
    assert enriched.row.field is None
