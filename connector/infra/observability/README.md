# connector/infra/observability

## Назначение

Инфраструктурные adapters observability-подсистемы поверх value-object layout/policy из `common/observability.py`.

Здесь живёт безопасная ретенция observability-артефактов: логов, отчётов и
планов. Sweeper запускается из CLI orchestration на старте команды и работает
только внутри component-partition каталогов.

## Файлы

| Файл | Назначение |
|---|---|
| `retention.py` | `ObservabilityRetentionSweeper` — safe sweep логов, отчётов и планов по age/backups внутри каталога компонента; не следует по симлинкам, использует marker-throttling |

## Зависимости

**Зависит от:** `common/observability.py`.  
**Используется:** `delivery/cli/containers.py`, `delivery/cli/runtime/orchestrator.py`.
