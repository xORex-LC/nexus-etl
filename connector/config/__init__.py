"""Configuration package.

Public API for the config layer. Import everything you need from here:

    from connector.config import load_app_settings, AppSettings, ApiSettings
"""

from connector.config.app_settings import (
    ApiSettings,
    AppSettings,
    DatasetSettings,
    ExecutionSettings,
    LoadedAppSettings,
    MatchingRuntimeSettings,
    ObservabilitySettings,
    PathsSettings,
    PendingSettings,
    RefreshSettings,
    VaultRolloutSettings,
    load_app_settings,
)
from connector.config.config import (
    Settings,
    SettingsConflictError,
    SettingsIssue,
    SettingsLoadError,
    SettingsParseError,
    SettingsSourceError,
    SettingsValidationError,
)
from connector.config.diagnostics import (
    translate_settings_issue,
    translate_settings_load_error,
    translate_settings_warnings,
)

__all__ = [
    # Slice dataclasses
    "ApiSettings",
    "AppSettings",
    "DatasetSettings",
    "ExecutionSettings",
    "LoadedAppSettings",
    "MatchingRuntimeSettings",
    "ObservabilitySettings",
    "PathsSettings",
    "PendingSettings",
    "RefreshSettings",
    "VaultRolloutSettings",
    # Loader
    "load_app_settings",
    # Core model & errors
    "Settings",
    "SettingsConflictError",
    "SettingsIssue",
    "SettingsLoadError",
    "SettingsParseError",
    "SettingsSourceError",
    "SettingsValidationError",
    # Diagnostics bridge
    "translate_settings_issue",
    "translate_settings_load_error",
    "translate_settings_warnings",
]
