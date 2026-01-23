from __future__ import annotations

from connector.domain.ports.cache_repository import UpsertResult
from connector.infra.cache.handlers.base import CacheDatasetHandler
from connector.infra.cache.sqlite_engine import SqliteEngine


class EmployeesCacheHandler(CacheDatasetHandler):
    """
    Назначение/ответственность:
        Хранение кэша сотрудников (таблица users).
    """

    dataset = "employees"
    table_names = ("users",)

    def ensure_schema(self, engine: SqliteEngine) -> None:
        engine.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                _id TEXT PRIMARY KEY,
                _ouid INTEGER NOT NULL UNIQUE,
                personnel_number TEXT NOT NULL,
                last_name TEXT NOT NULL,
                first_name TEXT NOT NULL,
                middle_name TEXT NOT NULL,
                match_key TEXT NOT NULL,
                mail TEXT NOT NULL,
                user_name TEXT NOT NULL,
                phone TEXT,
                usr_org_tab_num TEXT NOT NULL,
                organization_id INTEGER NOT NULL,
                account_status TEXT,
                deletion_date TEXT,
                _rev TEXT,
                manager_ouid INTEGER,
                is_logon_disabled INTEGER,
                position TEXT,
                updated_at TEXT
            )
            """
        )
        engine.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_match_key ON users(match_key)")
        engine.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_ouid ON users(_ouid)")
        engine.execute("CREATE INDEX IF NOT EXISTS idx_users_personnel_number ON users(personnel_number)")
        engine.execute("CREATE INDEX IF NOT EXISTS idx_users_usr_org_tab_num ON users(usr_org_tab_num)")
        engine.execute("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(organization_id)")

    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult:
        existing = engine.fetchone("SELECT 1 FROM users WHERE _id = ?", (write_model.get("_id"),))
        params = {
            "_id": write_model.get("_id"),
            "_ouid": write_model.get("_ouid"),
            "personnel_number": write_model.get("personnel_number"),
            "last_name": write_model.get("last_name"),
            "first_name": write_model.get("first_name"),
            "middle_name": write_model.get("middle_name"),
            "match_key": write_model.get("match_key"),
            "mail": write_model.get("mail"),
            "user_name": write_model.get("user_name"),
            "phone": write_model.get("phone"),
            "usr_org_tab_num": write_model.get("usr_org_tab_num"),
            "organization_id": write_model.get("organization_id"),
            "account_status": write_model.get("account_status"),
            "deletion_date": write_model.get("deletion_date"),
            "_rev": write_model.get("_rev"),
            "manager_ouid": write_model.get("manager_ouid"),
            "is_logon_disabled": write_model.get("is_logon_disabled"),
            "position": write_model.get("position"),
            "updated_at": write_model.get("updated_at"),
        }

        if existing:
            engine.execute(
                """
                UPDATE users
                SET _ouid = :_ouid,
                    personnel_number = :personnel_number,
                    last_name = :last_name,
                    first_name = :first_name,
                    middle_name = :middle_name,
                    match_key = :match_key,
                    mail = :mail,
                    user_name = :user_name,
                    phone = :phone,
                    usr_org_tab_num = :usr_org_tab_num,
                    organization_id = :organization_id,
                    account_status = :account_status,
                    deletion_date = :deletion_date,
                    _rev = :_rev,
                    manager_ouid = :manager_ouid,
                    is_logon_disabled = :is_logon_disabled,
                    position = :position,
                    updated_at = :updated_at
                WHERE _id = :_id
                """,
                params,
            )
            return UpsertResult.UPDATED

        engine.execute(
            """
            INSERT INTO users(
                _id, _ouid, personnel_number, last_name, first_name, middle_name,
                match_key, mail, user_name, phone, usr_org_tab_num, organization_id,
                account_status, deletion_date, _rev, manager_ouid, is_logon_disabled, position, updated_at
            ) VALUES(
                :_id, :_ouid, :personnel_number, :last_name, :first_name, :middle_name,
                :match_key, :mail, :user_name, :phone, :usr_org_tab_num, :organization_id,
                :account_status, :deletion_date, :_rev, :manager_ouid, :is_logon_disabled, :position, :updated_at
            )
            """,
            params,
        )
        return UpsertResult.INSERTED

    def count_total(self, engine: SqliteEngine) -> int:
        row = engine.fetchone("SELECT COUNT(*) FROM users")
        return int(row[0]) if row else 0

    def count_by_table(self, engine: SqliteEngine) -> dict[str, int]:
        return {"users": self.count_total(engine)}

    def clear(self, engine: SqliteEngine) -> None:
        engine.execute("DELETE FROM users")
