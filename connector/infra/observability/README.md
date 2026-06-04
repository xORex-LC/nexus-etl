# connector/infra/observability

## Назначение

Инфраструктурные adapters observability-подсистемы поверх value-object layout/policy из `common/observability.py`.

На текущем этапе здесь живёт безопасная ретенция логов; следующие этапы смогут добавить runtime adapters для ledger и artifact maintenance.

## Файлы

| Файл | Назначение |
|---|---|
| `retention.py` | `ObservabilityRetentionSweeper` — safe sweep логов по age/backups внутри каталога компонента; не следует по симлинкам, использует marker-throttling |

## Зависимости

**Зависит от:** `common/observability.py`.  
**Используется:** `delivery/cli/containers.py` (DI seams), последующие runtime-фазы observability.
