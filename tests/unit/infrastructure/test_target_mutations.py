from __future__ import annotations

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.providers.ankey_rest.mutations import regenerate_target_id


def test_regenerate_target_id_updates_operation_params(monkeypatch: pytest.MonkeyPatch) -> None:
    import connector.infra.target.providers.ankey_rest.mutations as mutation_mod

    monkeypatch.setattr(mutation_mod.uuid, "uuid4", lambda: "regen-001")
    spec = RequestSpec.operation(
        alias="users.upsert",
        params={"target_id": "orig-001"},
        payload={"name": "Alice"},
    )

    mutated = regenerate_target_id(spec)

    assert mutated.operation_alias == "users.upsert"
    assert mutated.operation_params == {"target_id": "regen-001"}
    assert mutated.payload == {"name": "Alice"}
