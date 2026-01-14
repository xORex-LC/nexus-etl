from __future__ import annotations

import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value != 0 else 0
    raise ValueError("Invalid bool value for is_logon_disabled")


def upsertUser(conn: sqlite3.Connection, userRow: dict[str, Any]) -> str:
    """
    Вставляет или обновляет пользователя.
    """
    required_keys = [
        "_id",
        "_ouid",
        "personnel_number",
        "last_name",
        "first_name",
        "middle_name",
        "match_key",
        "mail",
        "user_name",
        "usr_org_tab_num",
        "organization_id",
    ]
    missing = [key for key in required_keys if userRow.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    existing = conn.execute("SELECT 1 FROM users WHERE _id = ?", (userRow["_id"],)).fetchone()
    params = {
        "_id": userRow.get("_id"),
        "_ouid": userRow.get("_ouid"),
        "personnel_number": userRow.get("personnel_number"),
        "last_name": userRow.get("last_name"),
        "first_name": userRow.get("first_name"),
        "middle_name": userRow.get("middle_name"),
        "match_key": userRow.get("match_key"),
        "mail": userRow.get("mail"),
        "user_name": userRow.get("user_name"),
        "phone": userRow.get("phone"),
        "usr_org_tab_num": userRow.get("usr_org_tab_num"),
        "organization_id": userRow.get("organization_id"),
        "account_status": userRow.get("account_status"),
        "deletion_date": userRow.get("deletion_date"),
        "_rev": userRow.get("_rev"),
        "manager_ouid": userRow.get("manager_ouid"),
        "is_logon_disabled": _bool_to_int(userRow.get("is_logon_disabled")),
        "position": userRow.get("position"),
        "updated_at": userRow.get("updated_at"),
    }

    if existing:
        conn.execute(
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
        return "updated"

    conn.execute(
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
    return "inserted"


def upsertOrganization(conn: sqlite3.Connection, orgRow: dict[str, Any]) -> str:
    """
    Вставляет или обновляет организацию.
    """
    if orgRow.get("_ouid") is None:
        raise ValueError("Missing required field: _ouid")

    existing = conn.execute("SELECT 1 FROM organizations WHERE _ouid = ?", (orgRow["_ouid"],)).fetchone()
    params = {
        "_ouid": orgRow.get("_ouid"),
        "code": orgRow.get("code"),
        "name": orgRow.get("name"),
        "parent_id": orgRow.get("parent_id"),
        "updated_at": orgRow.get("updated_at"),
    }

    if existing:
        conn.execute(
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
        return "updated"

    conn.execute(
        """
        INSERT INTO organizations(_ouid, code, name, parent_id, updated_at)
        VALUES(:_ouid, :code, :name, :parent_id, :updated_at)
        """,
        params,
    )
    return "inserted"


def getUserByMatchKey(conn: sqlite3.Connection, matchKey: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE match_key = ?", (matchKey,)).fetchone()
    return _row_to_dict(row)


def findUsersByMatchKey(conn: sqlite3.Connection, matchKey: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM users WHERE match_key = ?", (matchKey,)).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]


def getUserByPersonnelNumber(conn: sqlite3.Connection, personnelNumber: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE personnel_number = ?", (personnelNumber,)).fetchone()
    return _row_to_dict(row)


def getUserByOuid(conn: sqlite3.Connection, ouid: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE _ouid = ?", (ouid,)).fetchone()
    return _row_to_dict(row)


def getOrgByOuid(conn: sqlite3.Connection, ouid: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM organizations WHERE _ouid = ?", (ouid,)).fetchone()
    return _row_to_dict(row)


def getCounts(conn: sqlite3.Connection) -> tuple[int, int]:
    usersCount = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    orgCount = int(conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0])
    return usersCount, orgCount


def clearUsers(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM users")
    return cur.rowcount if cur.rowcount is not None else 0


def clearOrgs(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM organizations")
    return cur.rowcount if cur.rowcount is not None else 0


def getMetaValue(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row:
        return row[0]
    return None


def setMetaValue(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        return
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
