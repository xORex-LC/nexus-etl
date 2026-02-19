from __future__ import annotations

import pytest

from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.models import Identity
from connector.domain.transform_dsl import load_resolve_spec_for_dataset
from connector.domain.transform_dsl import load_sink_spec_for_dataset
from connector.domain.transform_dsl.specs import ResolveSpec
from connector.domain.transform_dsl.compilers.resolve import ResolveDsl
from connector.domain.transform.resolver.resolve_engine import ResolveEngine
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
        password="secret",
        personnel_number="100",
        manager_id="777",
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id=None,
    )


def test_resolve_dsl_compile_matches_employees_contract():
    spec = load_resolve_spec_for_dataset("employees")
    sink_spec = load_sink_spec_for_dataset("employees")
    compiled = ResolveDsl().compile(spec, sink_spec=sink_spec)

    assert len(compiled.link_rules.fields) == 2
    manager_rule = compiled.link_rules.fields[0]
    assert manager_rule.field == "manager_id"
    assert manager_rule.target_dataset == "employees"
    assert manager_rule.on_unresolved == "pending"
    assert tuple(key.name for key in manager_rule.resolve_keys) == ("match_key",)
    assert manager_rule.dedup_rules == (("organization_id",),)
    assert manager_rule.target_id_field == "_ouid"
    assert manager_rule.coerce == "int"

    assert compiled.resolve_rules.diff_policy is not None
    assert compiled.resolve_rules.build_source_ref is not None
    assert compiled.resolve_rules.secret_fields_for_op is not None
    assert compiled.resolve_rules.secret_lifecycle is not None
    assert compiled.resolve_rules.secret_lifecycle.mode == "persistent"
    assert compiled.resolve_rules.secret_lifecycle.delete_on_success is False


def test_resolve_dsl_requires_sink_when_from_sink_enabled():
    spec = load_resolve_spec_for_dataset("employees")
    with pytest.raises(ValueError):
        ResolveDsl().compile(spec)


def test_resolve_spec_rejects_empty_resolve_keys():
    with pytest.raises(Exception):
        ResolveSpec.model_validate(
            {
                "dataset": "employees",
                "resolve": {
                    "desired_state": {"mode": "project_fields", "fields": ["email"]},
                    "diff": {"mode": "compare_fields", "fields": [{"field": "email"}]},
                    "links": [
                        {
                            "field": "manager_id",
                            "target_dataset": "employees",
                            "resolve_keys": [],
                        }
                    ],
                },
            }
        )


def test_resolve_spec_rejects_invalid_on_unresolved():
    with pytest.raises(Exception):
        ResolveSpec.model_validate(
            {
                "dataset": "employees",
                "resolve": {
                    "desired_state": {"mode": "project_fields", "fields": ["email"]},
                    "diff": {"mode": "compare_fields", "fields": [{"field": "email"}]},
                    "links": [
                        {
                            "field": "manager_id",
                            "target_dataset": "employees",
                            "resolve_keys": [{"name": "match_key", "field": "manager_id"}],
                            "on_unresolved": "skip",
                        }
                    ],
                },
            }
        )


def test_resolve_dsl_compiled_rules_behavior():
    sample_row = _sample_row()
    identity = Identity(primary="match_key", values={"match_key": "k1"})
    existing = {
        "mail": "old@example.com",
        "phone": "+222",
        "position": "Lead",
        "manager_ouid": 123,
        "organization_id": 55,
        "is_logon_disabled": True,
    }
    desired = {
        "email": "user@example.com",
        "phone": "+111",
        "position": "Engineer",
        "organization_id": 20,
        "manager_id": "777",
        "password": "secret",
    }

    compiled = ResolveDsl().compile(
        load_resolve_spec_for_dataset("employees"),
        sink_spec=load_sink_spec_for_dataset("employees"),
    )

    # DSL rules behavior assertions (no legacy fallback source).
    desired_from_builder = compiled.resolve_rules.build_desired_state(sample_row, None)
    assert desired_from_builder["email"] == "user@example.com"
    assert desired_from_builder["usr_org_tab_num"] == "TAB-100"
    assert "password" not in desired_from_builder
    assert "target_id" not in desired_from_builder

    assert compiled.resolve_rules.build_source_ref(identity) == {"match_key": "k1"}
    assert compiled.resolve_rules.diff_policy(existing, desired) == {
        "mail": "user@example.com",
        "phone": "+111",
        "position": "Engineer",
        "organization_id": 20,
        "manager_id": "777",
        "is_logon_disable": None,
    }
    assert compiled.resolve_rules.secret_fields_for_op("create", desired, existing) == ["password"]
    assert compiled.resolve_rules.secret_fields_for_op("update", desired, existing) == []
    assert compiled.resolve_rules.secret_lifecycle is not None
    assert compiled.resolve_rules.secret_lifecycle.mode == "persistent"


def test_resolve_dsl_compiles_ephemeral_secret_lifecycle():
    spec = ResolveSpec.model_validate(
        {
            "dataset": "employees",
            "resolve": {
                "desired_state": {"mode": "project_fields", "fields": ["email"]},
                "diff": {"mode": "compare_fields", "fields": [{"field": "email"}]},
                "secrets": {
                    "mode": "by_op",
                    "create": ["password"],
                    "update": [],
                    "lifecycle": {
                        "mode": "ephemeral",
                        "delete_on_success": True,
                        "ttl_seconds": 300,
                    },
                },
            },
        }
    )

    compiled = ResolveDsl().compile(spec, sink_spec=load_sink_spec_for_dataset("employees"))
    lifecycle = compiled.resolve_rules.secret_lifecycle
    assert lifecycle is not None
    assert lifecycle.mode == "ephemeral"
    assert lifecycle.delete_on_success is True
    assert lifecycle.ttl_seconds == 300


def test_resolve_engine_wraps_lookup_core():
    spec = load_resolve_spec_for_dataset("employees")
    engine = ResolveEngine(
        spec=spec,
        cache_gateway=None,
        settings=None,
        catalog=build_catalog("employees", strict=True),
        sink_spec=load_sink_spec_for_dataset("employees"),
    )
    assert engine.resolve_rules.diff_policy is not None
    assert len(engine.link_rules.fields) == 2
