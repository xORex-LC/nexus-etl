from __future__ import annotations

from connector.domain.ports.cache.models import PendingLink
from connector.usecases.common.identity_sync import IdentityIndexSyncer


class RuntimeStub:
    def __init__(self, pending_by_key: dict[str, list[PendingLink]] | None = None) -> None:
        self.pending_by_key = pending_by_key or {}
        self.upsert_calls: list[tuple[str, str, str]] = []
        self.marked: list[int] = []

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        self.upsert_calls.append((dataset, identity_key, resolved_id))

    def list_pending_for_key(self, dataset: str, lookup_key: str) -> list[PendingLink]:
        _ = dataset
        return list(self.pending_by_key.get(lookup_key, []))

    def mark_resolved(self, pending_id: int) -> None:
        self.marked.append(pending_id)


def _pending(pending_id: int, *, lookup_key: str) -> PendingLink:
    return PendingLink(
        pending_id=pending_id,
        dataset="employees",
        source_row_id="row-1",
        field="manager_id",
        lookup_key=lookup_key,
        status="pending",
        attempts=0,
        created_at=None,
        last_attempt_at=None,
        expires_at=None,
        reason=None,
        payload=None,
    )


def test_sync_skips_when_resolved_id_missing() -> None:
    runtime = RuntimeStub()
    syncer = IdentityIndexSyncer(runtime=runtime, identity_keys={"employees": {"match_key"}})

    syncer.sync(dataset="employees", resolved_id=None, key_values={"match_key": "mk-1"})

    assert runtime.upsert_calls == []
    assert runtime.marked == []


def test_sync_skips_empty_key_values() -> None:
    runtime = RuntimeStub()
    syncer = IdentityIndexSyncer(runtime=runtime, identity_keys={"employees": {"match_key", "organization_id"}})

    syncer.sync(
        dataset="employees",
        resolved_id="101",
        key_values={"match_key": "   ", "organization_id": None},
    )

    assert runtime.upsert_calls == []
    assert runtime.marked == []


def test_sync_upserts_and_resolves_pending_links() -> None:
    lookup_key = "match_key:mgr-1"
    runtime = RuntimeStub(pending_by_key={lookup_key: [_pending(10, lookup_key=lookup_key), _pending(11, lookup_key=lookup_key)]})
    syncer = IdentityIndexSyncer(runtime=runtime, identity_keys={"employees": {"match_key"}})

    syncer.sync(dataset="employees", resolved_id=42, key_values={"match_key": "mgr-1"})

    assert runtime.upsert_calls == [("employees", lookup_key, "42")]
    assert runtime.marked == [10, 11]


def test_id_field_for_uses_dataset_override() -> None:
    runtime = RuntimeStub()
    syncer = IdentityIndexSyncer(runtime=runtime, identity_id_fields={"employees": "employee_id"})

    assert syncer.id_field_for("employees") == "employee_id"
    assert syncer.id_field_for("organizations") == "_id"
