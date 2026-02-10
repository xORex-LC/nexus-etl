# Cache Architecture

## Scope
Док фиксирует финальную архитектуру cache-слоя:
1. Что является каноническим API для разных слоев.
2. Как устроены lifecycle/transaction границы.
3. Как расширять cache (новые репозитории и backend).
4. Какие архитектурные guardrails уже внедрены.

## Finalized Model

### Layer contracts
1. Канонический runtime API внутри `infra/wiring`: `SqliteCacheGateway` с namespace-доступом:
   - `gateway.cache`
   - `gateway.identity`
   - `gateway.pending`
2. Канонический API для `domain/usecases`: role-based порты из `connector/domain/ports/cache/roles.py`.
3. `domain/usecases` не импортируют `connector.infra.cache.*` и не создают `Sqlite*` напрямую.

### Infra composition
1. `SqliteCacheGateway` остается infra-facade и lifecycle boundary.
2. Внутри фасада 3 специализированных репозитория:
   - `SqliteCacheRepository`
   - `SqliteIdentityRepository`
   - `SqlitePendingLinksRepository`
3. Role adapters вынесены в `connector/infra/cache/roles/`:
   - `admin.py`
   - `enrich_lookup.py`
   - `planning_runtime.py`
   - `apply_runtime.py`
   - `cache_refresh.py`
   - `bundle.py` (сборка role-портов поверх gateway)

### Infra tree (final)
```text
connector/infra/cache/
  cache_gateway.py
  cache_spec.py
  roles/
    admin.py
    enrich_lookup.py
    planning_runtime.py
    apply_runtime.py
    cache_refresh.py
    bundle.py
  repository/
    cache_repository.py
    identity_repository.py
    pending_links_repository.py
  backends/
    sqlite/
      db.py
      engine.py
      schema.py
      handlers/
        base.py
        generic_handler.py
```

### Lifecycle and ownership
1. Production сборка: `SqliteCacheGateway.open(settings, cache_specs)`.
2. Test/integration сборка: `SqliteCacheGateway.from_engine(engine, cache_specs)`.
3. Gateway реализует context manager:
   - `__enter__` возвращает gateway;
   - `__exit__` вызывает `close()`.
4. Ownership:
   - `open(...)` -> gateway владеет connection (`owns_connection=True`);
   - `from_engine(...)` -> connection управляется снаружи (`owns_connection=False`).

### Transaction model
1. `gateway.transaction()` всегда делегируется в общий `engine.transaction()`.
2. Добавлен guardrail: все вложенные репозитории обязаны использовать тот же `SqliteEngine`.
3. Это обеспечивает единый unit-of-work через `cache + identity + pending`.

## Why This Model
Решение закрывает конфликт двух стилей API:
1. В runtime нужен читаемый namespaced фасад (`gateway.cache.*`).
2. В домене нужны role-based контракты (SRP, узкие зависимости).

Выбранный компромисс:
1. Gateway не становится доменной зависимостью.
2. Role adapters выступают boundary-слоем между доменом и runtime facade.
3. Устранен дрейф между flat API и namespaced API.

## What Was Removed as Legacy
1. Transitional flat-proxy API на `SqliteCacheGateway`.
2. Legacy factory alias `build_sqlite_cache_gateway(...)`.
3. Монолитный `connector/infra/cache/role_ports.py` (заменен на `infra/cache/roles/*`).
4. Прямой infra-wiring cache внутри `usecases/*`.

## Extension Strategy
1. Новые cache-фичи добавляются через новый repository + role-adapter по необходимости.
2. Gateway остается точкой composition/lifecycle, а не местом дублирования всего API.
3. Для backend-эволюции:
   - `Postgres` рассматривается как реалистичная замена SQLite для persistent/query сценариев.
   - `Redis` рассматривается как ускоритель/ephemeral runtime state, не как drop-in для snapshot/query semantics SQLite.

## Architecture Tests
Файл: `tests/architecture/test_cache_layer_boundaries.py`.

Эти тесты проверяют:
1. `domain/*` не импортирует `connector.infra.cache`.
2. `usecases/*` не импортирует `connector.infra.cache`.
3. `SqliteCacheGateway` импортируется только в допустимых местах (infra/wiring/tests).
4. Legacy factory imports не возвращаются.

Назначение:
1. Зафиксировать архитектурные границы как автоматические guardrails.
2. Ловить regressions на CI, а не в ручном ревью.

## Optional Next Step
Если нужно усилить import-graph дисциплину:
1. добавить `import-linter` контракты как дополнительный static gate;
2. оставить `pytest` архитектурные тесты как основной runtime guard.
