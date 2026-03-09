from __future__ import annotations

from dataclasses import dataclass

from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval, VaultRotationPolicy
from connector.usecases.management.vault import (
    VaultKeyManagementResult,
    VaultKeyManagementStatus,
    VaultMaintenanceUseCase,
)


@dataclass
class _FakeKeyManagement:
    status_snapshot: VaultKeyManagementStatus
    rotate_result: VaultKeyManagementResult
    bridge_result: VaultKeyManagementResult | None = None
    rotate_calls: list[str] | None = None
    finalize_calls: list[str] | None = None
    status_calls: int = 0

    def __post_init__(self) -> None:
        self.rotate_calls = self.rotate_calls or []
        self.finalize_calls = self.finalize_calls or []

    def status(self) -> VaultKeyManagementStatus:
        self.status_calls += 1
        return self.status_snapshot

    def rotate_and_rewrap(self, *, run_id: str | None = None) -> VaultKeyManagementResult:
        self.rotate_calls.append(str(run_id))
        return self.rotate_result

    def finalize_inflight_bridge(self, *, run_id: str | None = None) -> VaultKeyManagementResult | None:
        self.finalize_calls.append(str(run_id))
        return self.bridge_result


def test_run_if_due_noop_when_not_due() -> None:
    key_management = _FakeKeyManagement(
        status_snapshot=VaultKeyManagementStatus(
            key_versions=("mk_2026",),
            active_key_version="mk_2026",
            bridge_keyring=False,
            dek_total=1,
            dek_rewrap_required=0,
            last_rotated_at="2026-03-05T00:00:00+00:00",
            last_rotation_result="ok",
            last_rotation_reason="rotate_completed",
            last_rotation_run_id="r-prev",
        ),
        rotate_result=VaultKeyManagementResult(
            operation="rotate",
            run_id="unused",
            active_key_version="mk_new",
            dek_rewrapped_count=1,
            bridge_key_count=2,
            final_key_count=1,
            rotated_at="2026-03-05T01:00:00+00:00",
        ),
    )
    usecase = VaultMaintenanceUseCase(
        key_management=key_management,
        rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
        now_utc=lambda: "2026-03-06T00:00:00+00:00",
        run_id_factory=lambda: "maintenance-run-001",
    )

    result = usecase.run_if_due()

    assert result.action == "no_op"
    assert result.due is False
    assert result.changed is False
    assert key_management.rotate_calls == []
    assert key_management.finalize_calls == []


def test_run_if_due_runs_rotate_when_due() -> None:
    key_management = _FakeKeyManagement(
        status_snapshot=VaultKeyManagementStatus(
            key_versions=("mk_2025",),
            active_key_version="mk_2025",
            bridge_keyring=False,
            dek_total=2,
            dek_rewrap_required=0,
            last_rotated_at="2025-01-01T00:00:00+00:00",
            last_rotation_result="ok",
            last_rotation_reason="rotate_completed",
            last_rotation_run_id="r-prev",
        ),
        rotate_result=VaultKeyManagementResult(
            operation="rotate",
            run_id="maintenance-run-002",
            active_key_version="mk_2026",
            dek_rewrapped_count=2,
            bridge_key_count=2,
            final_key_count=1,
            rotated_at="2026-03-06T00:00:00+00:00",
        ),
    )
    usecase = VaultMaintenanceUseCase(
        key_management=key_management,
        rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
        now_utc=lambda: "2026-03-06T00:00:00+00:00",
        run_id_factory=lambda: "maintenance-run-002",
    )

    result = usecase.run_if_due()

    assert result.action == "rotate"
    assert result.due is True
    assert result.changed is True
    assert result.active_key_version == "mk_2026"
    assert result.dek_rewrapped_count == 2
    assert key_management.rotate_calls == ["maintenance-run-002"]
    assert key_management.finalize_calls == []


def test_run_if_due_prioritizes_bridge_finalize() -> None:
    key_management = _FakeKeyManagement(
        status_snapshot=VaultKeyManagementStatus(
            key_versions=("mk_new", "mk_old"),
            active_key_version="mk_new",
            bridge_keyring=True,
            dek_total=2,
            dek_rewrap_required=2,
            last_rotated_at=None,
            last_rotation_result="rotating",
            last_rotation_reason="rotate_in_progress",
            last_rotation_run_id="r-prev",
        ),
        rotate_result=VaultKeyManagementResult(
            operation="rotate",
            run_id="unused",
            active_key_version="unused",
            dek_rewrapped_count=0,
            bridge_key_count=0,
            final_key_count=0,
            rotated_at=None,
        ),
        bridge_result=VaultKeyManagementResult(
            operation="rotate",
            run_id="maintenance-run-003",
            active_key_version="mk_new",
            dek_rewrapped_count=2,
            bridge_key_count=2,
            final_key_count=1,
            rotated_at="2026-03-06T00:00:00+00:00",
        ),
    )
    usecase = VaultMaintenanceUseCase(
        key_management=key_management,
        rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
        now_utc=lambda: "2026-03-06T00:00:00+00:00",
        run_id_factory=lambda: "maintenance-run-003",
    )

    result = usecase.run_if_due()

    assert result.action == "bridge_finalize"
    assert result.bridge_detected is True
    assert result.changed is True
    assert result.active_key_version == "mk_new"
    assert key_management.finalize_calls == ["maintenance-run-003"]
    assert key_management.rotate_calls == []
