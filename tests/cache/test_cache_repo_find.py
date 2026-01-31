from __future__ import annotations

from pathlib import Path

from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.datasets.cache_registry import list_cache_specs


def _build_repo(tmp_path: Path) -> SqliteCacheRepository:
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    engine = SqliteEngine(conn)
    cache_specs = list_cache_specs()
    ensure_cache_ready(engine, cache_specs)
    return SqliteCacheRepository(engine, cache_specs)


def test_find_exact_and_include_deleted(tmp_path: Path):
    repo = _build_repo(tmp_path)
    with repo.transaction():
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
    with repo.transaction():
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
