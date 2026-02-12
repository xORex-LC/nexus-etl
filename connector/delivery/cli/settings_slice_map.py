from __future__ import annotations

from typing import Final

# Фаза 1: фиксируем в wiring целевой контракт command/use-case -> settings slices.
# На этом этапе карта используется как метаданные контракта (без смены runtime-логики).

COMMAND_SETTINGS_SLICE_MAP: Final[dict[str, tuple[str, ...]]] = {
    "cache-refresh": ("RefreshSettings", "ApiSettings", "DatasetSettings", "ObservabilitySettings", "PathsSettings"),
    "cache-status": ("DatasetSettings", "ObservabilitySettings", "PathsSettings"),
    "cache-clear": ("DatasetSettings", "ObservabilitySettings", "PathsSettings"),
    "mapping": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "normalize": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "enrich": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "match": ("DatasetSettings", "MatchingRuntimeSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "resolve": ("DatasetSettings", "MatchingRuntimeSettings", "PendingSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "import-plan": ("DatasetSettings", "MatchingRuntimeSettings", "PendingSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "import-apply": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings", "PathsSettings"),
    "check-api": ("ApiSettings", "ObservabilitySettings", "PathsSettings"),
}

USECASE_SETTINGS_SLICE_MAP: Final[dict[str, tuple[str, ...]]] = {
    "CacheRefreshUseCase": ("RefreshSettings", "ApiSettings", "DatasetSettings", "ObservabilitySettings"),
    "CacheStatusUseCase": ("DatasetSettings", "ObservabilitySettings"),
    "CacheClearUseCase": ("DatasetSettings", "ObservabilitySettings"),
    "MappingUseCase": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings"),
    "NormalizeUseCase": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings"),
    "EnrichUseCase": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings"),
    "MatchUseCase": ("DatasetSettings", "MatchingRuntimeSettings", "ExecutionSettings", "ObservabilitySettings"),
    "ResolveUseCase": ("DatasetSettings", "MatchingRuntimeSettings", "PendingSettings", "ExecutionSettings", "ObservabilitySettings"),
    "ImportPlanService": ("DatasetSettings", "MatchingRuntimeSettings", "PendingSettings", "ExecutionSettings", "ObservabilitySettings"),
    "ImportApplyService": ("DatasetSettings", "ExecutionSettings", "ObservabilitySettings"),
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

