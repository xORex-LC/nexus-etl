from __future__ import annotations

from connector.domain.secrets.vault_rollout_policy import (
    ROLLOUT_REASON_CANARY_DATASET_FILTERED,
    ROLLOUT_REASON_CANARY_PERCENT_ZERO,
    ROLLOUT_REASON_MODE_OFF,
    ROLLOUT_REASON_NOT_REQUESTED,
    ROLLOUT_REASON_STAGING_DRY_RUN,
    VaultRolloutPolicySettings,
    compute_canary_bucket,
    evaluate_vault_rollout,
)


def test_rollout_policy_skips_when_vault_not_requested() -> None:
    decision = evaluate_vault_rollout(
        settings=VaultRolloutPolicySettings(mode="full"),
        requested_vault=False,
        dataset="employees",
        run_id="run-1",
        command_name="import-apply",
    )
    assert decision.vault_enabled is False
    assert decision.force_dry_run is False
    assert decision.reason == ROLLOUT_REASON_NOT_REQUESTED


def test_rollout_policy_off_blocks_vault_path() -> None:
    decision = evaluate_vault_rollout(
        settings=VaultRolloutPolicySettings(mode="off"),
        requested_vault=True,
        dataset="employees",
        run_id="run-1",
        command_name="import-plan",
    )
    assert decision.vault_enabled is False
    assert decision.reason == ROLLOUT_REASON_MODE_OFF


def test_rollout_policy_staging_forces_dry_run_for_import_apply() -> None:
    decision = evaluate_vault_rollout(
        settings=VaultRolloutPolicySettings(mode="staging_dry_run"),
        requested_vault=True,
        dataset="employees",
        run_id="run-1",
        command_name="import-apply",
    )
    assert decision.vault_enabled is True
    assert decision.force_dry_run is True
    assert decision.reason == ROLLOUT_REASON_STAGING_DRY_RUN


def test_rollout_policy_canary_blocks_dataset_outside_allowlist() -> None:
    decision = evaluate_vault_rollout(
        settings=VaultRolloutPolicySettings(
            mode="canary",
            canary_percent=100,
            canary_datasets=("organizations",),
        ),
        requested_vault=True,
        dataset="employees",
        run_id="run-1",
        command_name="import-apply",
    )
    assert decision.vault_enabled is False
    assert decision.reason == ROLLOUT_REASON_CANARY_DATASET_FILTERED


def test_rollout_policy_canary_percent_zero_blocks_all_runs() -> None:
    decision = evaluate_vault_rollout(
        settings=VaultRolloutPolicySettings(
            mode="canary",
            canary_percent=0,
            canary_datasets=("employees",),
        ),
        requested_vault=True,
        dataset="employees",
        run_id="run-1",
        command_name="import-apply",
    )
    assert decision.vault_enabled is False
    assert decision.reason == ROLLOUT_REASON_CANARY_PERCENT_ZERO


def test_canary_bucket_is_deterministic() -> None:
    first = compute_canary_bucket(seed="seed-1", dataset="employees", run_id="run-1")
    second = compute_canary_bucket(seed="seed-1", dataset="employees", run_id="run-1")
    assert first == second
    assert 0 <= first <= 99
