from __future__ import annotations

from connector.domain.ports.cache_repository import UpsertResult
from connector.infra.cache.handlers.base import CacheDatasetHandler
from connector.infra.cache.sqlite_engine import SqliteEngine


class OrganizationsCacheHandler(CacheDatasetHandler):
    """
    Назначение/ответственность:
        Хранение кэша организаций (таблица organizations).
    """

    dataset = "organizations"
    table_names = ("organizations",)

    def ensure_schema(self, engine: SqliteEngine) -> None:
        engine.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                _ouid INTEGER PRIMARY KEY,
                code TEXT,
                name TEXT,
                parent_id INTEGER,
                updated_at TEXT
            )
            """
        )
        engine.execute("CREATE INDEX IF NOT EXISTS idx_org_parent ON organizations(parent_id)")

    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult:
        existing = engine.fetchone("SELECT 1 FROM organizations WHERE _ouid = ?", (write_model.get("_ouid"),))
        params = {
            "_ouid": write_model.get("_ouid"),
            "code": write_model.get("code"),
            "name": write_model.get("name"),
            "parent_id": write_model.get("parent_id"),
            "updated_at": write_model.get("updated_at"),
        }
        if existing:
            engine.execute(
                """
                UPDATE organizations
                SET code = :code,
                    name = :name,
                    parent_id = :parent_id,
                    updated_at = :updated_at
                WHERE _ouid = :_ouid
                """,
                params,
            )
            return UpsertResult.UPDATED

        engine.execute(
            """
            INSERT INTO organizations(_ouid, code, name, parent_id, updated_at)
            VALUES(:_ouid, :code, :name, :parent_id, :updated_at)
            """,
            params,
        )
        return UpsertResult.INSERTED

    def count_total(self, engine: SqliteEngine) -> int:
        row = engine.fetchone("SELECT COUNT(*) FROM organizations")
        return int(row[0]) if row else 0

    def count_by_table(self, engine: SqliteEngine) -> dict[str, int]:
        return {"organizations": self.count_total(engine)}

    def clear(self, engine: SqliteEngine) -> None:
        engine.execute("DELETE FROM organizations")
