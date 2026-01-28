from __future__ import annotations

from dataclasses import dataclass

from connector.domain.transform.enricher import Enricher
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.normalized import NormalizedEmployeesRow


@dataclass
class _DummyEnrichDeps:
    identity_lookup = None

    def find_user_by_id(self, _resource_id: str):
        return None

    def find_user_by_usr_org_tab_num(self, _tab_num: str):
        return None

    def find_org_by_ouid(self, _ouid: int):
        return {"_ouid": _ouid}


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
        resource_id=None,
    )
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    result = enricher.enrich(_build_result(row))

    assert result.errors == []
    assert result.match_key is not None
    assert result.match_key.value == "Doe|John|M|100"
    assert result.row.resource_id is not None
    assert result.row.usr_org_tab_num is not None
    assert result.secret_candidates.get("password")


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
        resource_id="RID-1",
    )
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), None, "employees")
    result = enricher.enrich(_build_result(row))

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" in codes
    assert result.match_key is None


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
        resource_id="RID-1",
    )
    secret_store = _DummySecretStore()
    enricher = Enricher(EmployeesEnricherSpec(), _DummyEnrichDeps(), secret_store, "employees", run_id="run-1")
    result = enricher.enrich(_build_result(row, {"password": "secret"}))

    assert result.errors == []
    assert secret_store.calls
    dataset, match_key, secrets, run_id = secret_store.calls[0]
    assert dataset == "employees"
    assert match_key == "Doe|John|M|100"
    assert secrets == {"password": "secret"}
    assert run_id == "run-1"
