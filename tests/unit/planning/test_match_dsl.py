from __future__ import annotations

from types import SimpleNamespace

import pytest

from connector.domain.transform_dsl import load_match_spec_for_dataset
from connector.domain.dependency_tree import TopologyMatchMode
from connector.domain.transform_dsl.specs import MatchSpec
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform_dsl.compilers.match import MatchDsl
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform_dsl.compilers.resolve import ResolveRules
from connector.domain.diagnostics.catalog import build_catalog


def _sample_row() -> dict:
    return {
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
        "target_id": None,
    }


def _sample_context() -> MatchContext:
    return MatchContext(
        line_no=1,
        match_key="Doe|John|M|100",
        match_key_complete=True,
    )


def test_match_dsl_compile_matches_employees_dsl_contract():
    compiled = MatchDsl().compile(load_match_spec_for_dataset("employees"))

    assert compiled.ignored_fields == {
        "updated_at",
        "_rev",
        "deletion_date",
        "account_status",
    }
    assert compiled.source_dedup.enabled is True
    assert compiled.source_dedup.on_duplicate == "warn"
    assert compiled.source_dedup.on_conflict == "error"
    assert compiled.fuzzy.enabled is False
    assert compiled.fuzzy.top_k == 3
    assert tuple(rule.name for rule in compiled.identity_rules) == ("match_key",)

    row = _sample_row()
    context = _sample_context()
    identity0 = compiled.identity_rules[0].build_identity(row, context)
    assert identity0.primary == "match_key"
    assert identity0.values.get("match_key") == "Doe|John|M|100"
    assert compiled.topology is None


def test_match_dsl_compile_matches_organizations_topology_policy() -> None:
    compiled = MatchDsl().compile(load_match_spec_for_dataset("organizations"))

    assert compiled.topology is not None
    assert compiled.topology.enabled is True
    assert compiled.topology.apply_on == "ambiguous_only"
    assert compiled.topology.on_missing_topology == "hard_error"
    assert compiled.topology.comparison_ladder == (
        TopologyMatchMode.EXACT_CANONICAL_PATH,
        TopologyMatchMode.EXACT_LEAF_PARENT_CHAIN,
        TopologyMatchMode.EXACT_LEAF_ROOT_DEPTH,
    )


def test_match_spec_rejects_invalid_thresholds():
    with pytest.raises(Exception):
        MatchSpec.model_validate(
            {
                "dataset": "employees",
                "match": {
                    "identity_rules": [
                        {"name": "match_key", "fields": ["match_key"]},
                    ],
                    "fuzzy": {
                        "enabled": True,
                        "accept_threshold": 0.5,
                        "review_threshold": 0.8,
                    },
                },
            }
        )


def test_match_spec_rejects_invalid_top_k():
    with pytest.raises(Exception):
        MatchSpec.model_validate(
            {
                "dataset": "employees",
                "match": {
                    "identity_rules": [
                        {"name": "match_key", "fields": ["match_key"]},
                    ],
                    "fuzzy": {"top_k": 0},
                },
            }
        )


def test_match_spec_rejects_mismatched_comparators_and_weights():
    with pytest.raises(Exception):
        MatchSpec.model_validate(
            {
                "dataset": "employees",
                "match": {
                    "identity_rules": [
                        {"name": "match_key", "fields": ["match_key"]},
                    ],
                    "fuzzy": {
                        "enabled": True,
                        "comparators": {"email": "casefold"},
                        "weights": {"first_name": 1.0},
                    },
                },
            }
        )


def test_match_spec_rejects_enabled_topology_without_ladder() -> None:
    with pytest.raises(Exception):
        MatchSpec.model_validate(
            {
                "dataset": "organizations",
                "match": {
                    "identity_rules": [
                        {"name": "match_key", "fields": ["match_key"]},
                    ],
                    "topology": {
                        "enabled": True,
                        "apply_on": "ambiguous_only",
                        "on_missing_topology": "skip",
                        "comparison_ladder": [],
                    },
                },
            }
        )


def test_match_engine_wraps_match_core():
    spec = load_match_spec_for_dataset("employees")
    engine = MatchEngine(
        spec=spec,
        dataset="employees",
        cache_gateway=SimpleNamespace(
            find=lambda *_args, **_kwargs: [],
            set_runtime_state=lambda *_args, **_kwargs: None,
            get_runtime_state=lambda *_args, **_kwargs: None,
            clear_runtime_scope=lambda *_args, **_kwargs: None,
        ),
        resolve_rules=ResolveRules(build_desired_state=lambda *_: {}),
        include_deleted=False,
        catalog=build_catalog("employees", strict=True),
    )
    assert engine.matching_rules.identity_rules
