"""
Тесты PendingExpiryService — sweep + drain expired pending links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from connector.domain.ports.cache.models import PendingLink, PendingStatus
from connector.domain.transform.resolver.pending_expiry_service import PendingExpiryService
from connector.domain.transform.resolver.resolve_deps import ResolverSettings


def _make_link(pending_id: int = 1) -> PendingLink:
    return PendingLink(
        pending_id=pending_id,
        dataset="employees",
        source_row_id=f"row-{pending_id}",
        field="manager_id",
        lookup_key="match_key:user-1",
        status=PendingStatus.EXPIRED,
        attempts=1,
        created_at=None,
        last_attempt_at=None,
        expires_at=None,
        reason="expired",
        payload=None,
    )


@dataclass
class FakeResolveGateway:
    """Стаб ResolveRuntimePort для тестов."""

    sweep_calls: list[str] = field(default_factory=list)
    sweep_result: list[PendingLink] = field(default_factory=list)

    def sweep_expired(self, now: str, *, reason: str | None = None) -> list[PendingLink]:
        self.sweep_calls.append(now)
        return list(self.sweep_result)

    def transaction(self):
        raise NotImplementedError

    def find_candidates(self, *args, **kwargs):
        return []

    def add_pending(self, *args, **kwargs):
        return 0

    def list_pending_rows(self, *args, **kwargs):
        return []

    def mark_resolved_for_source(self, *args, **kwargs):
        pass

    def mark_conflict(self, *args, **kwargs):
        pass

    def touch_attempt(self, *args, **kwargs):
        return 0

    def purge_stale(self, *args, **kwargs):
        return 0


def _settings(interval: int = 60) -> ResolverSettings:
    return ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=interval,
        pending_on_expire="warn",
        pending_allow_partial=False,
        pending_retention_days=7,
    )


def test_drain_empty_returns_empty_list():
    gw = FakeResolveGateway()
    service = PendingExpiryService(cache_gateway=gw)
    assert service.drain_expired() == []


def test_sweep_with_zero_interval_does_nothing():
    gw = FakeResolveGateway(sweep_result=[_make_link()])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=0))
    service.sweep()
    assert gw.sweep_calls == []
    assert service.drain_expired() == []


def test_sweep_without_settings_does_nothing():
    gw = FakeResolveGateway(sweep_result=[_make_link()])
    service = PendingExpiryService(cache_gateway=gw, settings=None)
    service.sweep()
    assert gw.sweep_calls == []


def test_sweep_calls_gateway_on_first_call():
    gw = FakeResolveGateway(sweep_result=[_make_link(1)])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))
    service.sweep()
    assert len(gw.sweep_calls) == 1


def test_drain_returns_accumulated_links_and_clears_buffer():
    gw = FakeResolveGateway(sweep_result=[_make_link(1), _make_link(2)])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))
    service.sweep()
    expired = service.drain_expired()
    assert len(expired) == 2
    assert service.drain_expired() == []


def test_sweep_interval_guard_prevents_second_call():
    gw = FakeResolveGateway(sweep_result=[_make_link()])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))

    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    with patch("connector.domain.transform.resolver.pending_expiry_service.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        service.sweep()
        service.sweep()  # within interval — should be skipped

    assert len(gw.sweep_calls) == 1


def test_sweep_interval_guard_allows_call_after_interval():
    gw = FakeResolveGateway(sweep_result=[_make_link()])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    after = base + timedelta(seconds=61)

    with patch("connector.domain.transform.resolver.pending_expiry_service.datetime") as mock_dt:
        mock_dt.now.return_value = base
        service.sweep()
        mock_dt.now.return_value = after
        service.sweep()

    assert len(gw.sweep_calls) == 2


def test_sweep_with_empty_result_does_not_fill_buffer():
    gw = FakeResolveGateway(sweep_result=[])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))
    service.sweep()
    assert service.drain_expired() == []


def test_drain_clears_only_once():
    gw = FakeResolveGateway(sweep_result=[_make_link(1)])
    service = PendingExpiryService(cache_gateway=gw, settings=_settings(interval=60))
    service.sweep()
    first = service.drain_expired()
    second = service.drain_expired()
    assert len(first) == 1
    assert len(second) == 0
