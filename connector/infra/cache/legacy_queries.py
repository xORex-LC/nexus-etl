from __future__ import annotations

import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def findUsersByMatchKey(conn: sqlite3.Connection, matchKey: str) -> list[dict[str, Any]]:
    """
    Назначение:
        Legacy lookup пользователей по match_key.
    Контракт:
        Вход: matchKey
        Выход: список строк users в виде dict.
    """
    rows = conn.execute("SELECT * FROM users WHERE match_key = ?", (matchKey,)).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]

def findUserById(conn: sqlite3.Connection, resource_id: str) -> dict[str, Any] | None:
    """
    Назначение:
        Legacy lookup пользователя по resource_id (_id).
    """
    row = conn.execute("SELECT * FROM users WHERE _id = ?", (resource_id,)).fetchone()
    return _row_to_dict(row)


def findUserByUsrOrgTabNum(conn: sqlite3.Connection, tab_num: str) -> dict[str, Any] | None:
    """
    Назначение:
        Legacy lookup пользователя по usr_org_tab_num.
    """
    row = conn.execute("SELECT * FROM users WHERE usr_org_tab_num = ?", (tab_num,)).fetchone()
    return _row_to_dict(row)


def getOrgByOuid(conn: sqlite3.Connection, ouid: int) -> dict[str, Any] | None:
    """
    Назначение:
        Legacy lookup организации по _ouid.
    Контракт:
        Вход: ouid
        Выход: строка organizations в виде dict или None.
    """
    row = conn.execute("SELECT * FROM organizations WHERE _ouid = ?", (ouid,)).fetchone()
    return _row_to_dict(row)
