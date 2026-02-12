from __future__ import annotations

from types import SimpleNamespace

import pytest

from connector.domain.dsl.loader import load_match_spec_for_dataset
from connector.domain.dsl.specs import MatchSpec
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.matcher.match_dsl import MatchDsl
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform.matcher.rules import ResolveRules
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.diagnostics.catalog import build_catalog


def _sample_row() -> NormalizedEmployeesRow:
    return NormalizedEmployeesRow(
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
        target_id=None,
    )


def _sample_context() -> MatchContext:
    return MatchContext(
        line_no=1,
        match_key="Doe|John|M|100",
        match_key_complete=True,
        usr_org_tab_num="TAB-100",
    )


def test_match_dsl_compile_matches_employees_dsl_contract():
    compiled = MatchDsl().compile(load_match_spec_for_dataset("employees"))

    assert compiled.ignored_fields == {"updated_at", "_rev", "deletion_date", "account_status"}
    assert compiled.source_dedup.enabled is True
    assert compiled.source_dedup.on_duplicate == "warn"
    assert compiled.source_dedup.on_conflict == "error"
    assert compiled.fuzzy.enabled is False
    assert compiled.fuzzy.top_k == 3
    assert tuple(rule.name for rule in compiled.identity_rules) == ("match_key", "usr_org_tab_num")

    row = _sample_row()
    context = _sample_context()
    identity0 = compiled.identity_rules[0].build_identity(row, context)
    assert identity0.primary == "match_key"
    assert identity0.values.get("match_key") == "Doe|John|M|100"
    assert identity0.values.get("usr_org_tab_num") == "TAB-100"


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
