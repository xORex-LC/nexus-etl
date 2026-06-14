"""Observability shared kernel.

Кросс-слойные value-objects observability-подсистемы: логические компоненты
сервиса (`ServiceComponent`), чистый layout-резолвер имён артефактов
(`ObservabilityLayout`) и — рядом — машинно-авторитетная ECS-таксономия логов
(`taxonomy/`: actions/fields).

`common` — единственный санкционированный shared kernel: пакет импортируется
`domain`/`usecases`/`infra`/`delivery` одинаково. При будущем выделении
`nexus-observability` в отдельный пакет этот каталог поднимается целиком.

Публичный API сохраняется через re-export из `layout`, поэтому существующие
импорты `from connector.common.observability import ...` не меняются.
"""

from __future__ import annotations

from connector.common.observability.layout import (
    ClockMode,
    ComponentIdentity,
    LedgerBackendName,
    ObservabilityArtifactKind,
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ObservabilityRedactionPolicy,
    RuntimePathsLike,
    ServiceComponent,
)

__all__ = [
    "ClockMode",
    "ComponentIdentity",
    "LedgerBackendName",
    "ObservabilityArtifactKind",
    "ObservabilityLayout",
    "ObservabilityLayoutPolicy",
    "ObservabilityRedactionPolicy",
    "RuntimePathsLike",
    "ServiceComponent",
]
