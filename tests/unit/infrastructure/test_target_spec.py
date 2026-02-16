from __future__ import annotations

import pytest

from connector.infra.target.core.spec_models import (
    FaultRule,
    OperationSpec,
    RetryConfig,
    RetryRule,
    TargetSpec,
)
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec


def test_operation_alias_is_trimmed() -> None:
    operation = OperationSpec(
        alias="  users.upsert  ",
        expected_statuses=(200, 201),
        data={
            "method": "PUT",
            "path_template": "/ankey/managed/user/{target_id}",
        },
    )

    assert operation.alias == "users.upsert"


def test_operation_alias_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="operation alias must not be empty"):
        OperationSpec(
            alias="   ",
            expected_statuses=(200,),
            data={"method": "GET", "path_template": "/health"},
        )


def test_fault_rule_requires_matcher() -> None:
    with pytest.raises(ValueError, match="fault rule requires"):
        FaultRule(fault_kind="DATA")


def test_retry_rule_requires_matcher() -> None:
    with pytest.raises(ValueError, match="retry rule requires"):
        RetryRule(directive="NO_RETRY")


def test_retry_rule_can_match_by_reason() -> None:
    rule = RetryRule(directive="RETRY_BACKOFF", match_reason="resourceexists", mutation="regenerate_target_id")
    assert rule.match_reason == "resourceexists"
    assert rule.mutation == "regenerate_target_id"


def test_retry_config_validates_backoff_bounds() -> None:
    with pytest.raises(ValueError, match="backoff_max must be greater or equal"):
        RetryConfig(backoff_base=2.0, backoff_max=1.0)


def test_target_spec_rejects_operation_alias_key_mismatch() -> None:
    spec = build_ankey_spec()
    payload = spec.model_dump()
    payload["operations"]["users.upsert"]["alias"] = "users.create"

    with pytest.raises(ValueError, match="operation alias key mismatch"):
        TargetSpec.model_validate(payload)
