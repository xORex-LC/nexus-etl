from __future__ import annotations

from connector.delivery.commands.import_apply_dry_run_executor import DryRunExecutor
from connector.domain.ports.target.execution import RequestSpec


def test_dry_run_executor_returns_ok_without_payload() -> None:
    executor = DryRunExecutor()

    result = executor.execute(
        RequestSpec.operation(
            alias="users.upsert",
            payload={"email": "u@example.com"},
            params={"target_id": "id-1"},
        )
    )

    assert result.ok is True
    assert result.answer_code is None
    assert result.response_payload is None
    assert result.error_code is None
    assert result.error_message is None
