from __future__ import annotations

from typing import Final

from connector.config.app_settings import (
    ApiSettings,
    DatasetSettings,
    ExecutionSettings,
    MatchingRuntimeSettings,
    ObservabilitySettings,
    PathsSettings,
    RefreshSettings,
    VaultRolloutSettings,
)
from connector.domain.transform.resolver.resolve_deps import ResolverSettings

COMMAND_SETTINGS_SLICE_MAP: Final[dict[str, tuple[type, ...]]] = {
    "cache-refresh": (RefreshSettings, ApiSettings, DatasetSettings, ObservabilitySettings, PathsSettings),
    "cache-status": (DatasetSettings, ObservabilitySettings, PathsSettings),
    "cache-clear": (DatasetSettings, ObservabilitySettings, PathsSettings),
    "mapping": (DatasetSettings, ExecutionSettings, ObservabilitySettings, PathsSettings),
    "normalize": (DatasetSettings, ExecutionSettings, ObservabilitySettings, PathsSettings),
    "enrich": (DatasetSettings, ExecutionSettings, ObservabilitySettings, PathsSettings, VaultRolloutSettings),
    "match": (DatasetSettings, MatchingRuntimeSettings, ExecutionSettings, ObservabilitySettings, PathsSettings),
    "resolve": (DatasetSettings, MatchingRuntimeSettings, ResolverSettings, ExecutionSettings, ObservabilitySettings, PathsSettings),
    "import-plan": (
        DatasetSettings,
        MatchingRuntimeSettings,
        ResolverSettings,
        ExecutionSettings,
        ObservabilitySettings,
        PathsSettings,
        VaultRolloutSettings,
    ),
    "import-apply": (DatasetSettings, ExecutionSettings, ObservabilitySettings, PathsSettings, VaultRolloutSettings),
    "check-api": (ApiSettings, ObservabilitySettings, PathsSettings),
}

USECASE_SETTINGS_SLICE_MAP: Final[dict[str, tuple[type, ...]]] = {
    "CacheRefreshUseCase": (RefreshSettings, ApiSettings, DatasetSettings, ObservabilitySettings),
    "CacheStatusUseCase": (DatasetSettings, ObservabilitySettings),
    "CacheClearUseCase": (DatasetSettings, ObservabilitySettings),
    "MappingUseCase": (DatasetSettings, ExecutionSettings, ObservabilitySettings),
    "NormalizeUseCase": (DatasetSettings, ExecutionSettings, ObservabilitySettings),
    "EnrichUseCase": (DatasetSettings, ExecutionSettings, ObservabilitySettings, VaultRolloutSettings),
    "MatchUseCase": (DatasetSettings, MatchingRuntimeSettings, ExecutionSettings, ObservabilitySettings),
    "ResolveUseCase": (DatasetSettings, MatchingRuntimeSettings, ResolverSettings, ExecutionSettings, ObservabilitySettings),
    "ImportPlanService": (
        DatasetSettings,
        MatchingRuntimeSettings,
        ResolverSettings,
        ExecutionSettings,
        ObservabilitySettings,
        VaultRolloutSettings,
    ),
    "ImportApplyService": (DatasetSettings, ExecutionSettings, ObservabilitySettings, VaultRolloutSettings),
}

COMMAND_TO_USECASE: Final[dict[str, str]] = {
    "cache-refresh": "CacheRefreshUseCase",
    "cache-status": "CacheStatusUseCase",
    "cache-clear": "CacheClearUseCase",
    "mapping": "MappingUseCase",
    "normalize": "NormalizeUseCase",
    "enrich": "EnrichUseCase",
    "match": "MatchUseCase",
    "resolve": "ResolveUseCase",
    "import-plan": "ImportPlanService",
    "import-apply": "ImportApplyService",
}
