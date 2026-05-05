from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.loader import _expand_enrich_templates
from connector.domain.transform_dsl.specs import EnrichSpec
from connector.domain.transform_dsl.compilers.enrich import EnricherDsl, build_enricher_spec_from_dsl
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


def _build_spec_from_yaml(tmp_path, raw: dict) -> EnrichSpec:
    path = tmp_path / "enrich.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EnrichSpec.model_validate(loaded)


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
                    "provider": {
                        "name": "cache.by_field",
                        "args": {
                            "dataset": "employees",
                            "field": "full_name",
                        },
                    },
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
    expanded = _expand_enrich_templates(raw)
    lookup = expanded["enrich"]["lookup"][0]
    assert lookup["provider"]["name"] == "cache.by_field"
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
                    "exists": {
                        "provider": {
                            "name": "cache.exists_by_field",
                            "args": {
                                "dataset": "employees",
                                "field": "usr_org_tab_num",
                            },
                        }
                    },
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
        class _CacheRepo:
            @staticmethod
            def find(dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
                _ = (dataset, include_deleted, mode)
                assert filters == {"full_name": "John Doe"}
                return [{"_id": "user-1"}]

        cache_gateway = _CacheRepo()

    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "provider": {
                        "name": "cache.by_field",
                        "args": {
                            "dataset": "employees",
                            "field": "full_name",
                        },
                    },
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
        class _CacheRepo:
            @staticmethod
            def find(dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
                _ = (dataset, include_deleted, mode)
                assert filters == {"full_name": "John Doe"}
                return [{"user": {"id": "nested-1"}}]

        cache_gateway = _CacheRepo()

    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "provider": {
                        "name": "cache.by_field",
                        "args": {
                            "dataset": "employees",
                            "field": "full_name",
                        },
                    },
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


def test_lookup_rule_requires_provider_code() -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                }
            ]
        },
    }

    with pytest.raises(DslLoadError) as exc_info:
        _build_enricher_spec(raw)
    assert exc_info.value.code == "ENRICH_DSL_LOOKUP_PROVIDER_MISSING"


def test_lookup_key_ops_fail_with_explicit_dsl_code() -> None:
    class _Deps:
        class _CacheRepo:
            @staticmethod
            def find(dataset: str, filters: dict[str, object], *, include_deleted: bool = False, mode: str = "exact"):
                _ = (dataset, filters, include_deleted, mode)
                return []

        cache_gateway = _CacheRepo()

    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_full_name",
                    "provider": {
                        "name": "cache.by_field",
                        "args": {
                            "dataset": "employees",
                            "field": "full_name",
                        },
                    },
                    "ops": [{"op": "to_int"}],
                }
            ]
        },
    }
    spec = _build_enricher_spec(raw)
    op = next(op for op in spec.operations if op.op_type == EnrichOperationType.LOOKUP)
    provider = op.providers[0]
    result = _make_result(row={"manager_full_name": "John Doe"})
    ctx = EnrichContext(dataset="employees")

    with pytest.raises(DslLoadError) as exc_info:
        provider.fetch(ctx, result, _Deps(), {})
    assert exc_info.value.code == "ENRICH_DSL_LOOKUP_KEY_OP_FAILED"


def test_generate_rule_accepts_build_when_then_on_conflict_contract(tmp_path) -> None:
    spec = _build_spec_from_yaml(
        tmp_path,
        {
            "dataset": "employees",
            "enrich": {
                "generate": [
                    {
                        "name": "user_name",
                        "target": "user_name",
                        "build": {
                            "source": "first_name",
                            "ops": [{"op": "transliterate"}],
                        },
                        "when": {
                            "source": "first_name",
                            "ops": [{"op": "contains_non_ascii"}],
                        },
                        "then": {
                            "sources": ["last_name", "middle_name"],
                            "ops": [{"op": "concat", "args": {"sep": ""}}],
                        },
                        "on_conflict": {
                            "strategy": "retry_with_suffixes",
                            "suffixes": ["_2", "_3"],
                        },
                    }
                ]
            },
        },
    )

    rule = spec.enrich.generate[0]
    assert rule.build is not None
    assert rule.build.source == "first_name"
    assert rule.when is not None
    assert rule.then is not None
    assert rule.on_conflict is not None
    assert rule.on_conflict.suffixes == ["_2", "_3"]


def test_source_ops_block_requires_exactly_one_source_shape(tmp_path) -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "generate": [
                {
                    "name": "user_name",
                    "target": "user_name",
                    "build": {
                        "source": "first_name",
                        "sources": ["first_name"],
                        "ops": [{"op": "trim"}],
                    },
                }
            ]
        },
    }

    with pytest.raises(ValidationError, match="exactly one of 'source' or 'sources' must be provided"):
        _build_spec_from_yaml(tmp_path, raw)


def test_then_requires_when(tmp_path) -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "generate": [
                {
                    "name": "user_name",
                    "target": "user_name",
                    "then": {
                        "source": "last_name",
                        "ops": [{"op": "trim"}],
                    },
                }
            ]
        },
    }

    with pytest.raises(ValidationError, match="'then' requires 'when'"):
        _build_spec_from_yaml(tmp_path, raw)


def test_retry_with_suffixes_requires_non_empty_suffixes(tmp_path) -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "generate": [
                {
                    "name": "user_name",
                    "target": "user_name",
                    "on_conflict": {
                        "strategy": "retry_with_suffixes",
                        "suffixes": [],
                    },
                }
            ]
        },
    }

    with pytest.raises(ValidationError, match="retry_with_suffixes requires non-empty suffixes"):
        _build_spec_from_yaml(tmp_path, raw)


def test_lookup_rule_rejects_generate_only_blocks(tmp_path) -> None:
    raw = {
        "dataset": "employees",
        "enrich": {
            "lookup": [
                {
                    "name": "manager_id",
                    "target": "manager_id",
                    "source": "manager_name",
                    "provider": {
                        "name": "cache.by_field",
                        "args": {"dataset": "employees", "field": "full_name"},
                    },
                    "build": {
                        "source": "manager_name",
                        "ops": [{"op": "trim"}],
                    },
                }
            ]
        },
    }

    with pytest.raises(ValidationError, match="lookup rules must not declare build/when/then/on_conflict"):
        _build_spec_from_yaml(tmp_path, raw)


def test_generate_rule_compiles_base_condition_append_and_conflict_policy() -> None:
    spec = _build_enricher_spec(
        {
            "dataset": "employees",
            "enrich": {
                "generate": [
                    {
                        "name": "user_name",
                        "target": "user_name",
                        "build": {
                            "source": "first_name",
                            "ops": [{"op": "transliterate"}],
                        },
                        "when": {
                            "source": "first_name",
                            "ops": [{"op": "contains_non_ascii"}],
                        },
                        "then": {
                            "sources": ["last_name", "middle_name"],
                            "ops": [
                                {
                                    "op": "map_each",
                                    "args": {
                                        "ops": [
                                            {"op": "transliterate"},
                                            {"op": "substring", "args": {"start": 0, "length": 1}},
                                        ]
                                    },
                                },
                                {"op": "compact"},
                                {"op": "concat", "args": {"sep": ""}},
                            ],
                        },
                        "on_conflict": {
                            "strategy": "retry_with_suffixes",
                            "suffixes": ["_2", "_3"],
                        },
                    }
                ]
            },
        }
    )

    op = spec.operations[0]
    result = _make_result(
        row={
            "first_name": "Иван",
            "last_name": "Иванов",
            "middle_name": "Иванович",
        }
    )

    assert op.generator is not None
    assert op.base_generator is not None
    assert op.condition is not None
    assert op.append_generator is not None
    assert op.conflict_policy is not None

    assert op.generator(result, object()) == "Ivan"
    assert op.base_generator(result, object()) == "Ivan"
    assert op.condition(result, object()) is True
    assert op.append_generator(result, object()) == "II"
    assert op.conflict_policy.strategy == "retry_with_suffixes"
    assert op.conflict_policy.suffixes == ("_2", "_3")
    assert op.conflict_policy.attempts == 3
    assert op.max_attempts == 3


def test_generate_rule_with_conflict_strategy_error_keeps_default_attempt_budget() -> None:
    spec = _build_enricher_spec(
        {
            "dataset": "employees",
            "enrich": {
                "generate": [
                    {
                        "name": "user_name",
                        "target": "user_name",
                        "source": "first_name",
                        "ops": [{"op": "trim"}],
                        "on_conflict": {
                            "strategy": "error",
                            "suffixes": [],
                        },
                        "max_attempts": 5,
                    }
                ]
            },
        }
    )

    op = spec.operations[0]

    assert op.conflict_policy is not None
    assert op.conflict_policy.strategy == "error"
    assert op.conflict_policy.attempts == 1
    assert op.max_attempts == 5


def test_fail_on_unknown_ops_covers_build_when_then_blocks() -> None:
    registry = OperationRegistry()
    register_core_ops(registry)
    dsl = EnricherDsl(
        registry=registry,
        options=EnrichDslBuildOptions(fail_on_unknown_ops=True),
    )
    spec = _build_spec(
        {
            "dataset": "employees",
            "enrich": {
                "generate": [
                    {
                        "name": "user_name",
                        "target": "user_name",
                        "build": {
                            "source": "first_name",
                            "ops": [{"op": "unknown_op"}],
                        },
                    }
                ]
            },
        }
    )

    with pytest.raises(DslLoadError) as exc_info:
        dsl.compile(spec)
    assert exc_info.value.code == "DSL_OP_UNKNOWN"
