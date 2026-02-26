from __future__ import annotations

from typing import Final

from connector.config.models import (
    ApiConfig,
    DatasetConfig,
    ExecutionConfig,
    MatchingRuntimeConfig,
    ObservabilityConfig,
    PathsConfig,
    RefreshConfig,
    ResolverConfig,
    VaultRolloutConfig,
)

COMMAND_SETTINGS_SLICE_MAP: Final[dict[str, tuple[type, ...]]] = {
    "cache-refresh": (RefreshConfig, ApiConfig, DatasetConfig, ObservabilityConfig, PathsConfig),
    "cache-status": (DatasetConfig, ObservabilityConfig, PathsConfig),
    "cache-clear": (DatasetConfig, ObservabilityConfig, PathsConfig),
    "mapping": (DatasetConfig, ExecutionConfig, ObservabilityConfig, PathsConfig),
    "normalize": (DatasetConfig, ExecutionConfig, ObservabilityConfig, PathsConfig),
    "enrich": (DatasetConfig, ExecutionConfig, ObservabilityConfig, PathsConfig, VaultRolloutConfig),
    "match": (DatasetConfig, MatchingRuntimeConfig, ExecutionConfig, ObservabilityConfig, PathsConfig),
    "resolve": (DatasetConfig, MatchingRuntimeConfig, ResolverConfig, ExecutionConfig, ObservabilityConfig, PathsConfig),
    "import-plan": (
        DatasetConfig,
        MatchingRuntimeConfig,
        ResolverConfig,
        ExecutionConfig,
        ObservabilityConfig,
        PathsConfig,
        VaultRolloutConfig,
    ),
    "import-apply": (DatasetConfig, ExecutionConfig, ObservabilityConfig, PathsConfig, VaultRolloutConfig),
    "check-api": (ApiConfig, ObservabilityConfig, PathsConfig),
}

USECASE_SETTINGS_SLICE_MAP: Final[dict[str, tuple[type, ...]]] = {
    "CacheRefreshUseCase": (RefreshConfig, ApiConfig, DatasetConfig, ObservabilityConfig),
    "CacheStatusUseCase": (DatasetConfig, ObservabilityConfig),
    "CacheClearUseCase": (DatasetConfig, ObservabilityConfig),
    "MappingUseCase": (DatasetConfig, ExecutionConfig, ObservabilityConfig),
    "NormalizeUseCase": (DatasetConfig, ExecutionConfig, ObservabilityConfig),
    "EnrichUseCase": (DatasetConfig, ExecutionConfig, ObservabilityConfig, VaultRolloutConfig),
    "MatchUseCase": (DatasetConfig, MatchingRuntimeConfig, ExecutionConfig, ObservabilityConfig),
    "ResolveUseCase": (DatasetConfig, MatchingRuntimeConfig, ResolverConfig, ExecutionConfig, ObservabilityConfig),
    "ImportPlanService": (
        DatasetConfig,
        MatchingRuntimeConfig,
        ResolverConfig,
        ExecutionConfig,
        ObservabilityConfig,
        VaultRolloutConfig,
    ),
    "ImportApplyService": (DatasetConfig, ExecutionConfig, ObservabilityConfig, VaultRolloutConfig),
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
