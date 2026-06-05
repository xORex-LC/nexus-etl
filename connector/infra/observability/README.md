# connector/infra/observability

## Назначение

Инфраструктурные adapters observability-подсистемы поверх value-object layout/policy из `common/observability.py`.

Здесь живут append-only run ledger и безопасная ретенция observability-артефактов:
логов, отчётов, планов и самого ledger. Sweeper запускается из CLI orchestration
на старте команды и работает только внутри component-partition каталогов.

## Файлы

| Файл | Назначение |
|---|---|
| `ledger.py` | `JsonlRunLedger` / `SqliteRunLedger` — best-effort индекс запусков `run_id -> status + artifact paths` по компоненту |
| `retention.py` | `ObservabilityRetentionSweeper` — safe sweep логов, отчётов, планов и ledger по age/backups внутри каталога компонента; не следует по симлинкам, использует marker-throttling |

## Зависимости

**Зависит от:** `common/observability.py`.  
**Используется:** `delivery/cli/containers.py`, `delivery/cli/runtime/orchestrator.py`.
