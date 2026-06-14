"""Юнит-тесты ECS processor и alias registry."""

from __future__ import annotations

import pytest

from connector.infra.logging.ecs import (
    STRUCTURAL_ROOTS,
    ecs_transform,
    field_aliases,
    validate_field_name_for_event_contract,
)

pytestmark = pytest.mark.unit


class _Logger:
    name = "tests.ecs"


def test_ecs_transform_maps_core_aliases_to_canonical_fields() -> None:
    payload = ecs_transform(
        _Logger(),
        "info",
        {
            "event": "Stage completed",
            "level": "info",
            "logger": "tests.pipeline",
            "action": "stage-completed",
            "dataset": "employees",
            "stage_name": "match",
            "items_count": 12,
            "duration_ns": 123456,
            "outcome": "success",
            "kind": "metric",
            "component": "planner",
        },
    )

    assert payload["message"] == "Stage completed"
    assert payload["event.action"] == "stage-completed"
    assert payload["event.dataset"] == "employees"
    assert payload["event.duration"] == 123456
    assert payload["event.outcome"] == "success"
    assert payload["event.kind"] == "metric"
    assert payload["nexus.stage.name"] == "match"
    assert payload["nexus.stage.items_count"] == 12
    assert payload["service.type"] == "planner"
    assert payload["log.logger"] == "tests.pipeline"
    assert payload["ecs.version"]


def test_ecs_transform_keeps_unknown_fields_under_labels() -> None:
    payload = ecs_transform(
        _Logger(),
        "info",
        {
            "event": "Unknown business fields",
            "row_ref": "row-1",
            "unsafe.value": {"b": 2, "a": 1},
        },
    )

    assert payload["labels.row_ref"] == "row-1"
    assert payload["labels.unsafe_value"] == '{"a": 1, "b": 2}'


def test_ecs_transform_handles_foreign_log_record_without_action() -> None:
    payload = ecs_transform(
        _Logger(),
        "error",
        {
            "event": "Foreign error",
            "level": "error",
        },
    )

    assert payload["message"] == "Foreign error"
    assert payload["log.level"] == "error"
    assert payload["log.logger"] == "tests.ecs"


def test_ecs_transform_merges_exception_stack_with_manual_error_code() -> None:
    payload = ecs_transform(
        _Logger(),
        "error",
        {
            "event": "Failed",
            "error_code": "STAGE_FAILED",
            "exception": [
                {
                    "type": "ValueError",
                    "value": "bad input",
                    "stack": ["traceback"],
                }
            ],
        },
    )

    assert payload["error.code"] == "STAGE_FAILED"
    assert payload["error.type"] == "ValueError"
    assert payload["error.message"] == "bad input"
    assert "error.stack_trace" in payload


@pytest.mark.parametrize("key", sorted(STRUCTURAL_ROOTS) + ["event.action"])
def test_event_contract_rejects_structural_roots_and_dotted_keys(key: str) -> None:
    with pytest.raises(ValueError):
        validate_field_name_for_event_contract(key)


def test_event_contract_allows_short_domain_aliases() -> None:
    validate_field_name_for_event_contract("stage_name")
    validate_field_name_for_event_contract("diag_code")


def test_taxonomy_aliases_cover_phase_one_lifecycle_fields() -> None:
    aliases = field_aliases()

    assert aliases["action"] == "event.action"
    assert aliases["dataset"] == "event.dataset"
    assert aliases["duration_ns"] == "event.duration"
    assert aliases["stage_name"] == "nexus.stage.name"
    assert aliases["items_count"] == "nexus.stage.items_count"
