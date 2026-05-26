# connector/domain/transform/resolver

## Назначение

Стадия разрешения конфликтов сопоставления. Обрабатывает `AMBIGUOUS`-записи и записи с незавершёнными `pending`-состояниями из предыдущих прогонов.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `resolve_engine.py` | `ResolveEngine` — итерирует поток через `ResolveCore` |
| `resolve_core.py` | `ResolveCore` — основная логика: читает `batch_index`, проверяет pending, формирует `ResolvedRow` |
| `pending_codec.py` | Сериализация/десериализация pending-записей для хранения в SQLite |
| `pending_expiry_service.py` | `PendingExpiryService` — TTL-проверка и пометка просроченных pending |
| `batch_index_service.py` | `IBatchIndexService` — интерфейс Singleton-сервиса батч-индекса для пары `ResolveContext`/`Resolve` стадий |

## Жизненный цикл pending

1. `ResolveContextStage` строит `batch_index` из сопоставленных записей
2. `ResolveStage` — для каждой записи: проверяет pending, решает создать/обновить/конфликт/ждать
3. Нерешённые pending хранятся в `identity.sqlite3` до следующего прогона
4. TTL контролируется `pending_ttl` и `max_attempts` из конфига

## Зависимости

**Зависит от:** `domain/transform/matcher/match_models.py`, `domain/transform_dsl/specs/resolve.py`, `domain/ports/cache/roles.py` (`ResolveRuntimePort`), `domain/diagnostics/`.  
**Используется:** `domain/transform/stages/stages.py` (`ResolveContextStage`, `ResolveStage`).
