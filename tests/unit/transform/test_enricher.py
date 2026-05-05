from __future__ import annotations

from dataclasses import dataclass

from connector.domain.transform.enrich import (
    CandidateValue,
    ConflictResolver,
    EnricherCore,
    EnricherEngine,
    EnrichOperationType,
    MergePolicy,
    RunWhenErrors,
    StrictnessPolicy,
    EnrichOutcome,
)
from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.compilers.enrich import (
    CompiledConflictPolicy,
    EnricherSpec,
    EnrichmentOperation,
    KeyRegistry,
)
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl import load_enrich_spec_for_dataset
from connector.domain.transform_dsl import load_sink_spec_for_dataset
from connector.domain.transform.ids.match_key import MatchKey
from connector.datasets.registry import get_spec
from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.dsl.registry import OperationRegistry, register_core_ops

CATALOG = build_catalog("employees", strict=True)


@dataclass
class _DummyEnrichDeps:
    cache_gateway: object
    identity_lookup = None


class _ConflictingTabDeps(_DummyEnrichDeps):
    pass


class _MemoryCacheRepo:
    def __init__(
        self,
        *,
        employees: list[dict[str, object]] | None = None,
        organizations: list[dict[str, object]] | None = None,
    ) -> None:
        self._rows = {
            "employees": employees or [],
            "organizations": organizations or [],
        }

    def find(self, dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
        _ = (include_deleted, mode)
        rows = self._rows.get(dataset, [])
        return [
            row
            for row in rows
            if all(row.get(key) == value for key, value in filters.items())
        ]

    def find_one(self, dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
        rows = self.find(dataset, filters, include_deleted=include_deleted, mode=mode)
        return rows[0] if rows else None


class _DummySecretStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], str | None]] = []

    def put_many(self, dataset: str, match_key: str, secrets: dict[str, str], run_id: str | None) -> None:
        self.calls.append((dataset, match_key, secrets, run_id))


def _build_enricher_from_dsl(
    deps: _DummyEnrichDeps,
    *,
    secret_store: _DummySecretStore | None = None,
    run_id: str | None = None,
) -> EnricherEngine:
    registry = OperationRegistry()
    register_core_ops(registry)
    return EnricherEngine(
        spec=load_enrich_spec_for_dataset("employees"),
        deps=deps,
        secret_store=secret_store,
        dataset="employees",
        catalog=CATALOG,
        registry=registry,
        options=EnrichDslBuildOptions(require_match_key=True),
        sink_spec=load_sink_spec_for_dataset("employees"),
        run_id=run_id,
    )


def _build_result(
    row: dict, secret_candidates: dict[str, str] | None = None
) -> TransformResult:
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
    row = {
        "email": None,
        "last_name": "Иванов",
        "first_name": "Иван",
        "middle_name": "Иванович",
        "is_logon_disable": False,
        "user_name": None,
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": "Org 20",
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": None,
        "target_id": None,
    }
    cache_repo = _MemoryCacheRepo(
        organizations=[{"_ouid": 20, "name": "Org 20"}],
    )
    enricher = _build_enricher_from_dsl(_DummyEnrichDeps(cache_gateway=cache_repo))
    result = enricher.enrich(_build_result(row))

    assert result.errors == ()
    assert result.match_key is not None
    assert result.match_key.value == "Иванов|Иван|Иванович|100"
    assert result.row["user_name"] == "IvanII"
    assert result.row["organization_id"] == 20
    assert result.row["target_id"] is not None
    assert result.row["usr_org_tab_num"] is not None
    assert len(str(result.row["usr_org_tab_num"])) == 8
    assert str(result.row["usr_org_tab_num"]).isdigit()
    assert result.secret_candidates == {}
    secret_fields = result.meta.get("secret_fields")
    assert secret_fields == ["password"]
    summary = result.meta.get("enrich_summary")
    assert summary is not None
    assert summary["operations_total"] >= 1
    assert summary["outcomes"].get("APPLIED", 0) >= 1


def test_enricher_reports_missing_match_key():
    row = {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": None,
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
        "target_id": "RID-1",
    }
    enricher = _build_enricher_from_dsl(_DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()))
    result = enricher.enrich(_build_result(row))

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" in codes
    assert result.match_key is None


def test_enricher_reports_secret_match_key_missing_when_store_needs_locator():
    row = {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": None,
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
        "target_id": "RID-1",
    }
    enricher = _build_enricher_from_dsl(_DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()))
    result = enricher.enrich(_build_result(row, {"password": "secret"}))

    codes = {issue.code for issue in result.errors}
    assert "SECRET_MATCH_KEY_MISSING" in codes
    assert result.match_key is None


def test_enricher_runs_only_allowed_ops_on_error():
    row = {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": None,
        "target_id": None,
    }
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
    enricher = _build_enricher_from_dsl(_DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()))
    enriched = enricher.enrich(result)

    assert enriched.match_key is not None
    assert enriched.row.get("target_id") is None
    assert enriched.row.get("usr_org_tab_num") is None
    summary = enriched.meta.get("enrich_summary")
    assert summary is not None
    assert summary["operations_total"] == 1


def test_enricher_writes_secrets_to_store():
    row = {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
        "target_id": "RID-1",
    }
    secret_store = _DummySecretStore()
    enricher = _build_enricher_from_dsl(
        _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()),
        secret_store=secret_store,
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
    row = {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "12345678",
        "target_id": None,
    }
    cache_repo = _MemoryCacheRepo(
        employees=[
            {
                "_id": "existing-1",
                "match_key": "OTHER",
                "usr_org_tab_num": "12345678",
            }
        ]
    )
    enricher = _build_enricher_from_dsl(_ConflictingTabDeps(cache_gateway=cache_repo))
    result = enricher.enrich(_build_result(row))

    codes = {issue.code for issue in result.errors}
    assert "USR_ORG_TAB_CONFLICT" in codes


def test_enricher_uses_cache_row_for_update_and_does_not_generate_password():
    row = {
        "email": None,
        "last_name": "Иванов",
        "first_name": "Иван",
        "middle_name": "Иванович",
        "is_logon_disable": False,
        "user_name": None,
        "phone": "+111",
        "password": None,
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": "Org 30",
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": None,
        "target_id": None,
    }
    cache_repo = _MemoryCacheRepo(
        employees=[
            {
                "_id": "existing-user-100",
                "match_key": "Иванов|Иван|Иванович|100",
                "mail": "ivan@example.com",
                "user_name": "IvanII",
                "phone": "+79990000000",
                "usr_org_tab_num": "87654321",
                "is_logon_disabled": True,
            }
        ],
        organizations=[{"_ouid": 30, "name": "Org 30"}],
    )
    secret_store = _DummySecretStore()
    enricher = _build_enricher_from_dsl(
        _DummyEnrichDeps(cache_gateway=cache_repo),
        secret_store=secret_store,
        run_id="run-update",
    )

    result = enricher.enrich(_build_result(row))

    assert result.errors == ()
    assert result.match_key is not None
    assert result.row["target_id"] == "existing-user-100"
    assert result.row["email"] == "ivan@example.com"
    assert result.row["user_name"] == "IvanII"
    assert result.row["usr_org_tab_num"] == "87654321"
    assert result.row["organization_id"] == 30
    assert result.meta.get("secret_fields") is None
    assert secret_store.calls == []


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
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
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
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
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
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
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


def test_enricher_no_candidates_warning_includes_field_rule_and_reason():
    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="email_from_cache",
                op_type=EnrichOperationType.LOOKUP,
                targets=("email",),
                providers=(),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_no_candidates=EnrichOutcome.WARNED),
                error_field="email",
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)

    enriched = enricher.enrich(_build_result({"email": None}))

    assert len(enriched.warnings) == 1
    warning = enriched.warnings[0]
    assert warning.code == "ENRICH_NO_CANDIDATES"
    assert warning.field == "email"
    assert warning.details == {
        "rule": "email_from_cache",
        "target": "email",
        "reason": "no_candidates",
    }


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
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
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


def test_enricher_warns_when_candidate_violates_sink_type():
    @dataclass
    class _Row:
        organization_id: int | str | None = 10

    def _compute(result, deps):
        _ = (result, deps)
        return {"organization_id": "not-a-number"}

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="type_check",
                op_type=EnrichOperationType.COMPUTE,
                targets=("organization_id",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.WARNED),
                merge_policy=MergePolicy(mode="recompute_always"),
                compute=_compute,
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(
        spec,
        _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()),
        None,
        "employees",
        catalog=CATALOG,
        sink_spec=load_sink_spec_for_dataset("employees"),
    )
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

    warning_codes = {issue.code for issue in enriched.warnings}
    assert "SINK_TYPE_INVALID" in warning_codes
    assert enriched.row.organization_id == 10


def test_enricher_compiled_generate_appends_then_value_when_condition_true():
    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="user_name",
                op_type=EnrichOperationType.GENERATE,
                targets=("user_name",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                base_generator=lambda _r, _d: "Ivan",
                condition=lambda _r, _d: True,
                append_generator=lambda _r, _d: "II",
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
    result = _build_result({"user_name": None})

    enriched = enricher.enrich(result)

    assert enriched.errors == ()
    assert enriched.row["user_name"] == "IvanII"


def test_enricher_allow_if_runs_before_conflict_policy():
    exists_calls: list[str] = []

    def _exists(_deps, value):
        exists_calls.append(value)
        if value == "Ivan":
            return {"match_key": "A"}
        return None

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="user_name",
                op_type=EnrichOperationType.GENERATE,
                targets=("user_name",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                base_generator=lambda _r, _d: "Ivan",
                exists=_exists,
                allow_if=lambda result, existing: result.match_key is not None and existing["match_key"] == result.match_key.value,
                conflict_policy=CompiledConflictPolicy(
                    strategy="retry_with_suffixes",
                    suffixes=("_2", "_3"),
                    attempts=3,
                ),
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)
    result = _build_result({"user_name": None})
    result = result.with_match_key(MatchKey("A"))

    enriched = enricher.enrich(result)

    assert enriched.errors == ()
    assert enriched.row["user_name"] == "Ivan"
    assert exists_calls == ["Ivan"]


def test_enricher_retries_suffixes_from_base_value() -> None:
    exists_calls: list[str] = []

    def _exists(_deps, value):
        exists_calls.append(value)
        if value in {"Ivan", "Ivan_2"}:
            return {"match_key": "OTHER"}
        return None

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="user_name",
                op_type=EnrichOperationType.GENERATE,
                targets=("user_name",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                base_generator=lambda _r, _d: "Ivan",
                exists=_exists,
                conflict_policy=CompiledConflictPolicy(
                    strategy="retry_with_suffixes",
                    suffixes=("_2", "_3"),
                    attempts=3,
                ),
                conflict_error_code="USR_ORG_TAB_CONFLICT",
                error_field="user_name",
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)

    enriched = enricher.enrich(_build_result({"user_name": None}))

    assert enriched.errors == ()
    assert enriched.row["user_name"] == "Ivan_3"
    assert exists_calls == ["Ivan", "Ivan_2", "Ivan_3"]


def test_enricher_returns_conflict_error_when_compiled_policy_is_exhausted():
    def _exists(_deps, value):
        _ = value
        return {"match_key": "OTHER"}

    spec = EnricherSpec(
        operations=(
            EnrichmentOperation(
                name="user_name",
                op_type=EnrichOperationType.GENERATE,
                targets=("user_name",),
                run_when_errors=RunWhenErrors.ALWAYS,
                strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
                base_generator=lambda _r, _d: "Ivan",
                exists=_exists,
                conflict_policy=CompiledConflictPolicy(
                    strategy="retry_with_suffixes",
                    suffixes=("_2",),
                    attempts=2,
                ),
                conflict_error_code="USR_ORG_TAB_CONFLICT",
                error_field="user_name",
            ),
        ),
        key_registry=KeyRegistry(builders={}),
    )
    enricher = EnricherCore(spec, _DummyEnrichDeps(cache_gateway=_MemoryCacheRepo()), None, "employees", catalog=CATALOG)

    enriched = enricher.enrich(_build_result({"user_name": None}))

    codes = {issue.code for issue in enriched.errors}
    assert "USR_ORG_TAB_CONFLICT" in codes


def test_employees_spec_sink_spec_has_dataset():
    spec = get_spec("employees")
    sink_spec = spec.build_spec_for("sink")

    assert sink_spec is not None
    assert sink_spec.dataset == "employees"
