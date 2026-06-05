"""CLI command → ServiceComponent mapping — delivery-level знание о командах.

Модуль отвечает за разрешение логического `ServiceComponent` по имени CLI-команды.
Это знание принадлежит delivery-слою (вокабуляр команд), а не cross-cutting `common/`:
`ServiceComponent` остаётся в `common/observability.py`, а привязка к именам команд — здесь.

Границы ответственности:
    - Разрешать `command_name` → `ServiceComponent` (fail-fast на неизвестной команде).

Вне ответственности:
    - Определение самого `ServiceComponent` и layout-резолвинг (живут в `common/observability.py`).
    - DI wiring и lifecycle (composition root в `containers.py`).
"""

from __future__ import annotations

from connector.common.observability import ServiceComponent

_DIRECT_COMMAND_COMPONENTS: dict[str, ServiceComponent] = {
    "mapping": ServiceComponent.MAPPER,
    "normalize": ServiceComponent.NORMALIZER,
    "enrich": ServiceComponent.ENRICHER,
    "match": ServiceComponent.MATCHER,
    "resolve": ServiceComponent.RESOLVER,
    "import-plan": ServiceComponent.PLANNER,
    "import-apply": ServiceComponent.APPLIER,
    "check-api": ServiceComponent.TOPOLOGY,
}


def component_for_command(command_name: str) -> ServiceComponent:
    """Разрешить логический компонент по имени CLI-команды."""
    normalized = command_name.strip().lower().replace("_", "-")
    direct = _DIRECT_COMMAND_COMPONENTS.get(normalized)
    if direct is not None:
        return direct
    if normalized.startswith("cache-"):
        return ServiceComponent.CACHE
    if normalized.startswith("vault-"):
        return ServiceComponent.VAULT
    raise KeyError(f"Unknown command name for component mapping: {command_name}")


__all__ = ["component_for_command"]
