from __future__ import annotations

from connector.domain.models import Identity, MatchResult, MatchStatus
from connector.infra.cache.repo import findUsersByMatchKey
from .protocols import IdentityLookup


class CacheEmployeeLookup(IdentityLookup):
    """
    Назначение/ответственность:
        Адаптер порта IdentityLookup, использующий локальный кэш/БД.
    Взаимодействия:
        Делегирует поиск в findUsersByMatchKey.
    Ограничения:
        Транзакционность/соединение остаются на уровне вызывающего кода.
    Примечание:
        TODO: Это employees-специфика (match_key). Нужна универсальная реализация,
        когда будет общий lookup между доменной identity и схемой хранения кэша.
    """

    def __init__(self, conn):
        self.conn = conn

    def match(self, identity: Identity, include_deleted: bool) -> MatchResult:
        """
        Назначение:
            Поиск пользователя в кэше по Identity (primary поддерживает только match_key).
        Контракт (вход/выход):
            - Вход: identity: Identity, include_deleted: bool.
            - Выход: MatchResult (found/not_found/conflict и кандидат).
        Ошибки/исключения:
            Пробрасывает исключения работы с БД.
        Алгоритм:
            Фильтрует удалённых (при необходимости) и определяет статус.
        """
        if identity.primary != "match_key":
            raise ValueError(f"Unsupported identity primary for employees: {identity.primary}")
        key_value = identity.values.get("match_key", "")
        candidates = findUsersByMatchKey(self.conn, key_value)
        if not include_deleted:
            candidates = [c for c in candidates if not _is_deleted(c)]

        if len(candidates) == 0:
            return MatchResult(status=MatchStatus.NOT_FOUND, candidate=None, candidates=[])
        if len(candidates) > 1:
            return MatchResult(status=MatchStatus.CONFLICT, candidate=None, candidates=candidates)
        return MatchResult(status=MatchStatus.MATCHED, candidate=candidates[0], candidates=candidates)


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
