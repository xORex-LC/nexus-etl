from __future__ import annotations

from connector.config.models import AppConfig
from connector.config.projections import to_cache_db_config
from pathlib import Path

from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.cache_spec import CacheSpec, FieldSpec


def _build_repo(tmp_path: Path) -> SqliteCacheRepository:
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    engine = open_sqlite(to_cache_db_config(AppConfig()), db_path)
    cache_specs = [_employees_cache_spec(), _organizations_cache_spec()]
    ensure_cache_ready(engine, cache_specs)
    return SqliteCacheRepository(engine, cache_specs)


def _employees_cache_spec() -> CacheSpec:
    return CacheSpec(
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
            FieldSpec(name="mail", type="string", nullable=True),
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
        unique_indexes=(("match_key",), ("usr_org_tab_num",)),
        indexes=(("personnel_number",), ("organization_id",)),
    )


def _organizations_cache_spec() -> CacheSpec:
    return CacheSpec(
        dataset="organizations",
        table="organizations",
        primary_key=("_ouid",),
        fields=(
            FieldSpec(name="_ouid", type="int", nullable=False),
            FieldSpec(name="code", type="string", nullable=False),
            FieldSpec(name="name", type="string", nullable=False),
            FieldSpec(name="parent_id", type="int", nullable=True),
            FieldSpec(name="updated_at", type="datetime", nullable=True),
        ),
        unique_indexes=(("code",),),
        indexes=(("name",),),
    )


def test_find_exact_and_include_deleted(tmp_path: Path):
    repo = _build_repo(tmp_path)
    with repo.engine.transaction():
        repo.upsert(
            "employees",
            {
                "_id": "u1",
                "_ouid": 1,
                "personnel_number": "100",
                "last_name": "Doe",
                "first_name": "John",
                "middle_name": "M",
                "match_key": "Doe|John|M|100",
                "mail": "john@example.com",
                "user_name": "jdoe",
                "phone": "+111",
                "usr_org_tab_num": "TAB-1",
                "organization_id": 10,
                "account_status": "active",
                "deletion_date": None,
                "_rev": None,
                "manager_ouid": None,
                "is_logon_disabled": None,
                "position": None,
                "updated_at": None,
            },
        )
        repo.upsert(
            "employees",
            {
                "_id": "u2",
                "_ouid": 2,
                "personnel_number": "101",
                "last_name": "Doe",
                "first_name": "Jane",
                "middle_name": "M",
                "match_key": "Doe|Jane|M|101",
                "mail": "jane@example.com",
                "user_name": "jane",
                "phone": None,
                "usr_org_tab_num": "TAB-2",
                "organization_id": 11,
                "account_status": "active",
                "deletion_date": "2025-01-01",
                "_rev": None,
                "manager_ouid": None,
                "is_logon_disabled": None,
                "position": None,
                "updated_at": None,
            },
        )

    active_only = repo.find("employees", {"_id": "u2"}, include_deleted=False)
    assert active_only == []

    with_deleted = repo.find("employees", {"_id": "u2"}, include_deleted=True)
    assert len(with_deleted) == 1
    assert with_deleted[0]["_id"] == "u2"


def test_find_like_and_in(tmp_path: Path):
    repo = _build_repo(tmp_path)
    with repo.engine.transaction():
        repo.upsert(
            "organizations",
            {"_ouid": 1, "code": "ORG-1", "name": "Alpha", "parent_id": None, "updated_at": None},
        )
        repo.upsert(
            "organizations",
            {"_ouid": 2, "code": "ORG-2", "name": "Beta", "parent_id": None, "updated_at": None},
        )

    like_rows = repo.find("organizations", {"name": "%Al%"}, mode="like")
    assert len(like_rows) == 1
    assert like_rows[0]["name"] == "Alpha"

    in_rows = repo.find("organizations", {"_ouid": [1, 2]}, mode="in")
    assert {row["_ouid"] for row in in_rows} == {1, 2}
