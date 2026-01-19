from __future__ import annotations

from connector.domain.models import MatchResult
from connector.infra.cache.repo import findUsersByMatchKey
from .protocols import EmployeeLookup


class CacheEmployeeLookup(EmployeeLookup):
    """
    Назначение/ответственность:
        Адаптер порта EmployeeLookup, использующий локальный кэш/БД.
    Взаимодействия:
        Делегирует поиск в findUsersByMatchKey.
    Ограничения:
        Транзакционность/соединение остаются на уровне вызывающего кода.
    """

    def __init__(self, conn):
        self.conn = conn

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult:
        """
        Назначение:
            Поиск пользователя по match_key в кэше.
        Контракт (вход/выход):
            - Вход: match_key: str, include_deleted: bool.
            - Выход: MatchResult (found/not_found/conflict и кандидат).
        Ошибки/исключения:
            Пробрасывает исключения работы с БД.
        Алгоритм:
            Фильтрует удалённых (при необходимости) и определяет статус.
        """
        candidates = findUsersByMatchKey(self.conn, match_key)
        if not include_deleted:
            candidates = [c for c in candidates if not _is_deleted(c)]

        if len(candidates) == 0:
            return MatchResult(status="not_found", candidate=None, candidates=[])
        if len(candidates) > 1:
            return MatchResult(status="conflict", candidate=None, candidates=candidates)
        return MatchResult(status="matched", candidate=candidates[0], candidates=candidates)


def _is_deleted(user_row) -> bool:
    status_raw = user_row.get("account_status")
    deletion_date = user_row.get("deletion_date")
    status_norm = str(status_raw).strip().lower() if status_raw is not None else ""
    deletion_norm = str(deletion_date).strip().lower() if deletion_date is not None else ""
    if status_norm == "deleted":
        return True
    if deletion_norm not in ("", "null"):
        return True
    return False
