from __future__ import annotations

from datetime import datetime, timezone

import pytest

from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval, VaultRotationPolicy


def test_rotation_policy_due_when_last_rotation_missing() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(days=30))
    assert policy.is_due(last_rotated_at=None, now_utc="2026-03-04T00:00:00+00:00") is True


def test_rotation_policy_not_due_before_interval() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(days=30))
    assert (
        policy.is_due(
            last_rotated_at="2026-03-01T00:00:00+00:00",
            now_utc="2026-03-20T00:00:00+00:00",
        )
        is False
    )


def test_rotation_policy_due_after_interval() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(days=30))
    assert (
        policy.is_due(
            last_rotated_at="2026-01-01T00:00:00+00:00",
            now_utc="2026-02-01T00:00:00+00:00",
        )
        is True
    )


def test_rotation_policy_month_shift_uses_calendar_logic() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(months=1))
    next_due = policy.next_due_at(last_rotated_at="2026-01-31T10:00:00+00:00")
    assert next_due == datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)


def test_rotation_policy_handles_utc_z_suffix() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(hours=1))
    assert policy.is_due(last_rotated_at="2026-03-04T00:00:00Z", now_utc="2026-03-04T01:00:00Z") is True


def test_rotation_interval_rejects_all_zeros() -> None:
    with pytest.raises(ValueError):
        VaultRotationInterval()


def test_rotation_policy_treats_naive_timestamp_as_utc() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(hours=1))
    assert (
        policy.is_due(
            last_rotated_at="2026-03-04T00:00:00",
            now_utc="2026-03-04T01:00:00+00:00",
        )
        is True
    )


def test_rotation_policy_rejects_invalid_iso_timestamp() -> None:
    policy = VaultRotationPolicy(interval=VaultRotationInterval(days=1))

    with pytest.raises(ValueError):
        policy.is_due(last_rotated_at="not-a-timestamp", now_utc="2026-03-04T00:00:00+00:00")
