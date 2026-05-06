"""
Unit-тесты для AppConfig и *Config моделей из connector/config/models.py.

Проверяют: defaults, Pydantic validation, frozen, extra="forbid",
Pydantic coerce (list → tuple), regression snapshot для критичных дефолтов.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from connector.config.models import (
    ApiConfig,
    AppConfig,
    DatasetConfig,
    MatchingRuntimeConfig,
    ResolverConfig,
    RuntimeConfig,
    VaultRolloutConfig,
)


def test_app_config_defaults_all_sections() -> None:
    """AppConfig() без аргументов инициализируется без ошибок, все секции присутствуют."""
    cfg = AppConfig()

    assert cfg.api is not None
    assert cfg.runtime is not None
    assert cfg.paths is not None
    assert cfg.observability is not None
    assert cfg.dataset is not None
    assert cfg.execution is not None
    assert cfg.refresh is not None
    assert cfg.matching_runtime is not None
    assert cfg.resolver is not None
    assert cfg.sqlite is not None
    assert cfg.dictionary is not None
    assert cfg.vault_rollout is not None


def test_api_config_port_range_validation() -> None:
    """port=0 → ValidationError; port=65535 → OK."""
    with pytest.raises(ValidationError):
        ApiConfig(host="h", port=0)

    cfg = ApiConfig(host="h", port=65535)
    assert cfg.port == 65535


def test_vault_rollout_config_mode_literal() -> None:
    """mode='staging_dry_run' → OK; mode='bad' → ValidationError."""
    vr = VaultRolloutConfig(mode="staging_dry_run")
    assert vr.mode == "staging_dry_run"

    with pytest.raises(ValidationError):
        VaultRolloutConfig(mode="bad")


def test_vault_rollout_config_canary_datasets_coerce() -> None:
    """YAML-list автоматически coerce-ится Pydantic v2 в tuple[str, ...]."""
    vr = VaultRolloutConfig.model_validate({"canary_datasets": ["ds1", "ds2"]})

    assert isinstance(vr.canary_datasets, tuple)
    assert vr.canary_datasets == ("ds1", "ds2")


def test_vault_rollout_config_canary_seed_default() -> None:
    """canary_seed default совпадает с доменным VaultRolloutPolicySettings."""
    assert VaultRolloutConfig().canary_seed == "vault-rollout-v1"


def test_resolver_config_has_resolve_batch_fields() -> None:
    """resolve_batch_size и resolve_flush_interval_ms присутствуют в ResolverConfig."""
    rc = ResolverConfig()

    assert rc.resolve_batch_size == 500
    assert rc.resolve_flush_interval_ms == 500


def test_matching_runtime_config_has_only_match_fields() -> None:
    """resolve_batch_* отсутствуют в MatchingRuntimeConfig (перенесены в ResolverConfig)."""
    mr = MatchingRuntimeConfig()

    assert not hasattr(mr, "resolve_batch_size")
    assert not hasattr(mr, "resolve_flush_interval_ms")
    # Match поля присутствуют
    assert mr.match_batch_size == 500
    assert mr.match_flush_interval_ms == 500


def test_dataset_config_accepts_registry_path() -> None:
    cfg = DatasetConfig(registry_path="./datasets/registry.yaml")

    assert cfg.registry_path == "./datasets/registry.yaml"


def test_runtime_config_defaults_follow_standalone_layout() -> None:
    cfg = RuntimeConfig()

    assert cfg.runtime_root == "."
    assert cfg.config_root == "./etc"
    assert cfg.datasets_root == "./datasets"
    assert cfg.dictionary_specs_root == "./etc/dictionaries"
    assert cfg.dictionary_data_root == "./dictionaries"
    assert cfg.source_projection_root == "./etc/source-projection"
    assert cfg.target_projection_root == "./etc/target-projection"


def test_app_config_extra_forbid_unknown_section() -> None:
    """AppConfig.model_validate({'unknown_section': 1}) → ValidationError."""
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"unknown_section": 1})


def test_api_config_extra_forbid_unknown_field() -> None:
    """ApiConfig(unknown=1) → ValidationError."""
    with pytest.raises(ValidationError):
        ApiConfig.model_validate({"unknown": 1})


def test_app_config_frozen_immutable() -> None:
    """Попытка присвоения поля замороженного объекта бросает исключение."""
    cfg = AppConfig()

    with pytest.raises(Exception):  # pydantic FrozenInstanceError
        cfg.api = ApiConfig()  # type: ignore[misc]


def test_app_config_defaults_regression() -> None:
    """Snapshot-тест: дефолты критичных полей не меняются тихо.

    Дефолты выровнены по текущим доменным значениям Settings / VaultRolloutThresholds.
    """
    cfg = AppConfig()

    # VaultRollout thresholds (aligned with VaultRolloutThresholds domain defaults)
    assert cfg.vault_rollout.row_failure_rate_threshold_pct == 5.0
    assert cfg.vault_rollout.error_rate_threshold_pct == 5.0
    assert cfg.vault_rollout.latency_regression_threshold_pct == 15.0
    assert cfg.vault_rollout.busy_timeout_rate_threshold_pct == 0.0
    assert cfg.vault_rollout.schema_changed_rate_threshold_pct == 0.0

    # Resolver (aligned with current Settings defaults)
    assert cfg.resolver.pending_max_attempts == 5
    assert cfg.resolver.pending_ttl_seconds == 120
    assert cfg.resolver.pending_on_expire == "error"
    assert cfg.resolver.pending_allow_partial is False
    assert cfg.resolver.pending_retention_days == 14

    # Vault rollout mode and canary seed
    assert cfg.vault_rollout.mode == "full"
    assert cfg.vault_rollout.canary_seed == "vault-rollout-v1"
    assert cfg.vault_rollout.canary_datasets == ()

    # SQLite defaults
    assert cfg.sqlite.journal_mode == "WAL"
    assert cfg.sqlite.busy_timeout_ms == 5000
    assert cfg.sqlite.vault_transaction_mode == "immediate"
    assert cfg.sqlite.cache_transaction_mode == "deferred"
    assert cfg.sqlite.vault_schema_retry_count == 2

    # Runtime/paths defaults
    assert cfg.runtime.datasets_root == "./datasets"
    assert cfg.paths.cache_dir == "./var/cache"
    assert cfg.paths.log_dir == "./var/logs"
    assert cfg.paths.report_dir == "./reports"
