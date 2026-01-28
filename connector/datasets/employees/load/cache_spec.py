from __future__ import annotations

from connector.infra.cache.cache_spec import CacheSpec, FieldSpec


employees_cache_spec = CacheSpec(
    dataset="employees",
    table="users",
    primary_key=("_id",),
    fields=(
        FieldSpec(name="_id", type="string", nullable=False),
        FieldSpec(name="_ouid", type="int", nullable=False),
        FieldSpec(name="personnel_number", type="string", nullable=False),
        FieldSpec(name="last_name", type="string", nullable=False),
        FieldSpec(name="first_name", type="string", nullable=False),
        FieldSpec(name="middle_name", type="string", nullable=False),
        FieldSpec(name="match_key", type="string", nullable=False),
        FieldSpec(name="mail", type="string", nullable=False),
        FieldSpec(name="user_name", type="string", nullable=False),
        FieldSpec(name="phone", type="string", nullable=True),
        FieldSpec(name="usr_org_tab_num", type="string", nullable=False),
        FieldSpec(name="organization_id", type="int", nullable=False),
        FieldSpec(name="account_status", type="string", nullable=True),
        FieldSpec(name="deletion_date", type="datetime", nullable=True),
        FieldSpec(name="_rev", type="string", nullable=True),
        FieldSpec(name="manager_ouid", type="int", nullable=True),
        FieldSpec(name="is_logon_disabled", type="bool", nullable=True),
        FieldSpec(name="position", type="string", nullable=True),
        FieldSpec(name="updated_at", type="datetime", nullable=True),
    ),
    unique_indexes=(
        ("_ouid",),
        ("match_key",),
        ("usr_org_tab_num",),
    ),
    indexes=(
        ("personnel_number",),
        ("organization_id",),
    ),
)
