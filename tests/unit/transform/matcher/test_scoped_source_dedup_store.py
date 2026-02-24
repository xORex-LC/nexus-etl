"""
Тесты ScopedSourceDedupStore — dedup хранилище с персистентным scoped-состоянием.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from connector.domain.transform.matcher.dedup_store import ScopedSourceDedupStore


@dataclass
class FakeMatchRuntime:
    """Минимальный стаб MatchRuntimePort для тестов."""

    _state: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def get_runtime_state(self, scope: str, dataset: str, state_key: str) -> str | None:
        return self._state.get((scope, dataset, state_key))

    def set_runtime_state(self, scope: str, dataset: str, state_key: str, state_value: str) -> None:
        self._state[(scope, dataset, state_key)] = state_value

    def clear_runtime_scope(self, scope: str) -> None:
        for key in [k for k in self._state if k[0] == scope]:
            del self._state[key]

    def find(self, *args, **kwargs):
        return []


def _store(gateway: FakeMatchRuntime, scope: str = "run:1", dataset: str = "employees") -> ScopedSourceDedupStore:
    return ScopedSourceDedupStore(cache_gateway=gateway, scope=scope, dataset=dataset)


def test_first_registration_returns_is_first():
    gw = FakeMatchRuntime()
    store = _store(gw)
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_first is True
    assert result.is_duplicate is False
    assert result.is_conflict is False


def test_first_registration_writes_to_cache_gateway():
    gw = FakeMatchRuntime()
    store = _store(gw, scope="run:1")
    store.check_and_register("key:1", "fp-aaa")
    assert gw.get_runtime_state("run:1", "employees", "key:1") == "fp-aaa"


def test_duplicate_within_same_store_returns_is_duplicate():
    gw = FakeMatchRuntime()
    store = _store(gw)
    store.check_and_register("key:1", "fp-aaa")
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_duplicate is True


def test_conflict_within_same_store_returns_is_conflict():
    gw = FakeMatchRuntime()
    store = _store(gw)
    store.check_and_register("key:1", "fp-aaa")
    result = store.check_and_register("key:1", "fp-bbb")
    assert result.is_conflict is True


def test_cross_instance_dedup_via_shared_gateway():
    """
    Два независимых ScopedSourceDedupStore с одним gateway и одним scope
    должны видеть состояние друг друга (cross-run dedup).
    Аналог test_source_dedup_reads_scoped_runtime_state_from_identity_repo.
    """
    gw = FakeMatchRuntime()

    store1 = _store(gw, scope="run:shared")
    store1.check_and_register("key:1", "fp-aaa")

    store2 = _store(gw, scope="run:shared")
    result = store2.check_and_register("key:1", "fp-aaa")

    assert result.is_duplicate is True


def test_cross_instance_conflict_via_shared_gateway():
    gw = FakeMatchRuntime()

    store1 = _store(gw, scope="run:shared")
    store1.check_and_register("key:1", "fp-aaa")

    store2 = _store(gw, scope="run:shared")
    result = store2.check_and_register("key:1", "fp-bbb")

    assert result.is_conflict is True


def test_different_scopes_are_isolated():
    gw = FakeMatchRuntime()

    store1 = _store(gw, scope="run:A")
    store1.check_and_register("key:1", "fp-aaa")

    store2 = _store(gw, scope="run:B")
    result = store2.check_and_register("key:1", "fp-aaa")

    assert result.is_first is True


def test_reset_clears_local_state_but_preserves_gateway():
    gw = FakeMatchRuntime()
    store = _store(gw, scope="run:1")
    store.check_and_register("key:1", "fp-aaa")

    store.reset()

    # Gateway state persists
    assert gw.get_runtime_state("run:1", "employees", "key:1") == "fp-aaa"

    # New store (different run) still detects as duplicate
    store2 = _store(gw, scope="run:1")
    result = store2.check_and_register("key:1", "fp-aaa")
    assert result.is_duplicate is True


def test_reset_then_reregister_writes_to_local():
    """
    После reset() локальный кэш очищен, но gateway уже имеет значение.
    Следующий check_and_register найдёт ключ через gateway и вернёт duplicate.
    """
    gw = FakeMatchRuntime()
    store = _store(gw, scope="run:1")
    store.check_and_register("key:1", "fp-aaa")
    store.reset()

    # Key still in gateway → duplicate
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_duplicate is True
