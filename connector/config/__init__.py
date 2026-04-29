"""Configuration package.

Public API for the config layer. Import everything you need from here:

    from connector.config import load_app_config, AppConfig, ApiConfig
"""

from connector.config.config import (
    SettingsIssue,
    SettingsLoadError,
    SettingsSourceError,
)
from connector.config.diagnostics import (
    translate_settings_issue,
    translate_settings_load_error,
    translate_settings_warnings,
)
from connector.config.loader import LoadedAppConfig, load_app_config
from connector.config.models import (
    ApiConfig,
    AppConfig,
    DatasetConfig,
    DictionaryConfig,
    ExecutionConfig,
    MatchingRuntimeConfig,
    ObservabilityConfig,
    PathsConfig,
    RefreshConfig,
    ResolverConfig,
    SqliteConfig,
    VaultManagementConfig,
    VaultRolloutConfig,
)
from connector.config.projections import (
    to_cache_db_config,
    to_identity_db_config,
    to_match_batch_settings,
    to_resolver_settings,
    to_vault_management_settings,
    to_vault_db_config,
    to_vault_rollout_policy_settings,
    to_vault_rollout_thresholds,
)

__all__ = [
    # Config models
    "ApiConfig",
    "AppConfig",
    "DatasetConfig",
    "DictionaryConfig",
    "ExecutionConfig",
    "MatchingRuntimeConfig",
    "ObservabilityConfig",
    "PathsConfig",
    "RefreshConfig",
    "ResolverConfig",
    "SqliteConfig",
    "VaultManagementConfig",
    "VaultRolloutConfig",
    # Loader
    "LoadedAppConfig",
    "load_app_config",
    # Projections
    "to_cache_db_config",
    "to_identity_db_config",
    "to_match_batch_settings",
    "to_resolver_settings",
    "to_vault_management_settings",
    "to_vault_db_config",
    "to_vault_rollout_policy_settings",
    "to_vault_rollout_thresholds",
    # Errors
    "SettingsIssue",
    "SettingsLoadError",
    "SettingsSourceError",
    # Diagnostics bridge
    "translate_settings_issue",
    "translate_settings_load_error",
    "translate_settings_warnings",
]
