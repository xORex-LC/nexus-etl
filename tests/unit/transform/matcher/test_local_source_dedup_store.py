"""
Тесты LocalSourceDedupStore — in-memory dedup хранилище.
"""

from __future__ import annotations

import pytest

from connector.domain.transform.matcher.dedup_store import LocalSourceDedupStore


def _store() -> LocalSourceDedupStore:
    return LocalSourceDedupStore()


def test_first_registration_returns_is_first():
    store = _store()
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_first is True
    assert result.is_duplicate is False
    assert result.is_conflict is False


def test_duplicate_same_fingerprint_returns_is_duplicate():
    store = _store()
    store.check_and_register("key:1", "fp-aaa")
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_duplicate is True
    assert result.is_first is False
    assert result.is_conflict is False


def test_conflict_different_fingerprint_returns_is_conflict():
    store = _store()
    store.check_and_register("key:1", "fp-aaa")
    result = store.check_and_register("key:1", "fp-bbb")
    assert result.is_conflict is True
    assert result.is_first is False
    assert result.is_duplicate is False


def test_different_keys_are_independent():
    store = _store()
    r1 = store.check_and_register("key:1", "fp-aaa")
    r2 = store.check_and_register("key:2", "fp-bbb")
    assert r1.is_first is True
    assert r2.is_first is True


def test_reset_clears_all_registered_keys():
    store = _store()
    store.check_and_register("key:1", "fp-aaa")
    store.check_and_register("key:2", "fp-bbb")
    store.reset()
    r1 = store.check_and_register("key:1", "fp-aaa")
    r2 = store.check_and_register("key:2", "fp-ccc")
    assert r1.is_first is True
    assert r2.is_first is True


def test_reset_allows_conflict_key_to_re_register():
    store = _store()
    store.check_and_register("key:1", "fp-aaa")
    store.check_and_register("key:1", "fp-bbb")  # conflict
    store.reset()
    result = store.check_and_register("key:1", "fp-ccc")
    assert result.is_first is True


def test_empty_store_on_construction():
    store = _store()
    result = store.check_and_register("any-key", "any-fp")
    assert result.is_first is True


def test_multiple_resets_are_idempotent():
    store = _store()
    store.check_and_register("key:1", "fp-aaa")
    store.reset()
    store.reset()
    result = store.check_and_register("key:1", "fp-aaa")
    assert result.is_first is True
