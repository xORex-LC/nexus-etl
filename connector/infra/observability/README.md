# connector/infra/observability

## Назначение

Инфраструктурные adapters observability-подсистемы поверх value-object layout/policy из `common/observability.py`.

На текущем этапе здесь живёт безопасная ретенция observability-артефактов:
логов, отчётов и планов. Sweeper работает только внутри component-partition
каталогов и не переключает orchestration call-sites сам по себе.

## Файлы

| Файл | Назначение |
|---|---|
| `retention.py` | `ObservabilityRetentionSweeper` — safe sweep логов, отчётов и планов по age/backups внутри каталога компонента; не следует по симлинкам, использует marker-throttling |

## Зависимости

**Зависит от:** `common/observability.py`.  
**Используется:** `delivery/cli/containers.py` (DI seams), последующие runtime-фазы observability.
