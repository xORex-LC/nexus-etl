"""
Назначение:
    Domain-порты dedup-стора для match-стадии.

    ISourceDedupStore — контракт хранилища, которое отслеживает,
    встречалась ли уже данная identity-запись в текущем (или предыдущих) прогонах.

    DedupOutcome — результат проверки, возвращаемый check_and_register().
"""

from __future__ import annotations

from typing import Protocol


class DedupOutcome(Protocol):
    """
    Назначение:
        Результат проверки и регистрации dedup-ключа.

    Атрибуты:
        is_first      — ключ встречается впервые; fingerprint сохранён.
        is_duplicate  — ключ уже видели с тем же fingerprint (дубликат).
        is_conflict   — ключ уже видели с другим fingerprint (конфликт).

    Инварианты:
        Ровно одно из трёх полей — True.
    """

    is_first: bool
    is_duplicate: bool
    is_conflict: bool


class ISourceDedupStore(Protocol):
    """
    Назначение:
        Хранилище source-dedup состояния для MatchCore.

    Контракт:
        - check_and_register() — атомарная проверка + регистрация.
        - reset() — сброс состояния перед новым прогоном (вызывается PlanningPipeline).

    Не знает о dataset-namespace: ключ строится снаружи (в MatchCore).
    """

    def check_and_register(self, key: str, fingerprint: str) -> DedupOutcome: ...

    def reset(self) -> None: ...


__all__ = ["DedupOutcome", "ISourceDedupStore"]
