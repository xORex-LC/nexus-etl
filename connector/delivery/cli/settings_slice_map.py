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
    VaultManagementConfig,
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
    "vault-management-init": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
    "vault-management-status": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
    "vault-management-rotate": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
    "vault-management-rewrap": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
    "vault-management-delete-key": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
    "vault-management-run-maintenance": (VaultManagementConfig, ObservabilityConfig, PathsConfig),
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
    "VaultKeyManagementUseCase": (VaultManagementConfig, ObservabilityConfig),
    "VaultMaintenanceUseCase": (VaultManagementConfig, ObservabilityConfig),
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
    "vault-management-init": "VaultKeyManagementUseCase",
    "vault-management-status": "VaultKeyManagementUseCase",
    "vault-management-rotate": "VaultKeyManagementUseCase",
    "vault-management-rewrap": "VaultKeyManagementUseCase",
    "vault-management-delete-key": "VaultKeyManagementUseCase",
    "vault-management-run-maintenance": "VaultMaintenanceUseCase",
}
