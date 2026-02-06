from __future__ import annotations

from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.dsl import loader as dsl_loader
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.dsl.specs import EnrichSpec
from connector.domain.transform.enrich.enricher_dsl import build_enricher_spec_from_dsl
from connector.domain.transform.enrich.models import EnrichContext, EnrichOperationType
from connector.domain.transform.ids.match_key import MatchKey


def _make_result(*, match_key: str | None = None, row: dict | None = None) -> TransformResult[dict]:
    record = SourceRecord(line_no=1, record_id="line:1", values={})
    return TransformResult(
        record=record,
        row=row or {},
        row_ref=None,
        match_key=MatchKey(match_key) if match_key else None,
        errors=[],
        warnings=[],
    )


def _build_spec(raw: dict) -> EnrichSpec:
    return EnrichSpec.model_validate(raw)


def _build_enricher_spec(raw: dict):
    registry = OperationRegistry()
    register_core_ops(registry)
    return build_enricher_spec_from_dsl(_build_spec(raw), registry=registry)


def test_expand_lookup_templates() -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup_templates": {
                "by_full_name": {
                    "lookup": "find_user_by_full_name",
                    "value_path": "_id",
                    "ops": [{"op": "trim"}],
                    "on_error": "warn",
                }
            },
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "template": "by_full_name",
                }
            ],
        },
    }
    expanded = dsl_loader._expand_enrich_templates(raw)
    lookup = expanded["enrich"]["lookup"][0]
    assert lookup["lookup"] == "find_user_by_full_name"
    assert lookup["value_path"] == "_id"
    assert lookup["source"] == "manager_full_name"
    assert "lookup_templates" not in expanded["enrich"]


def test_allow_if_equals_path() -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "generate": [
                {
                    "name": "usr_org_tab_num",
                    "target": "usr_org_tab_num",
                    "source": "usr_org_tab_num",
                    "ops": [{"op": "trim"}],
                    "exists": "find_user_by_usr_org_tab_num",
                    "allow_if": {"op": "equals_path", "args": {"left": "match_key", "right": "existing.match_key"}},
                }
            ]
        },
    }
    spec = _build_enricher_spec(raw)
    op = spec.operations[0]
    result = _make_result(match_key="A")

    assert op.allow_if is not None
    assert op.allow_if(result, {"match_key": "A"}) is True
    assert op.allow_if(result, {"match_key": "B"}) is False


def test_lookup_rule_builds_candidate_from_value_path() -> None:
    class _Deps:
        def find_user_by_full_name(self, value):
            assert value == "John Doe"
            return {"_id": "user-1"}

    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "lookup": "find_user_by_full_name",
                    "value_path": "_id",
                    "ops": [{"op": "trim"}],
                }
            ]
        },
    }
    spec = _build_enricher_spec(raw)
    op = next(op for op in spec.operations if op.op_type == EnrichOperationType.LOOKUP)
    provider = op.providers[0]
    result = _make_result(row={"manager_full_name": "  John Doe  "})
    ctx = EnrichContext(dataset="employees")

    candidates = provider.fetch(ctx, result, _Deps(), {})
    assert len(candidates) == 1
    assert candidates[0].field == "manager_id"
    assert candidates[0].value == "user-1"


def test_lookup_rule_supports_nested_value_path() -> None:
    class _Deps:
        def find_user_by_full_name(self, value):
            assert value == "John Doe"
            return {"user": {"id": "nested-1"}}

    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "lookup": "find_user_by_full_name",
                    "value_path": "user.id",
                }
            ]
        },
    }
    spec = _build_enricher_spec(raw)
    op = next(op for op in spec.operations if op.op_type == EnrichOperationType.LOOKUP)
    provider = op.providers[0]
    result = _make_result(row={"manager_full_name": "John Doe"})
    ctx = EnrichContext(dataset="employees")

    candidates = provider.fetch(ctx, result, _Deps(), {})
    assert len(candidates) == 1
    assert candidates[0].value == "nested-1"
