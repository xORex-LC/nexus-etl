# Stage/Engine Style (Current State + Next Migration)

## Scope
Док описывает:
1. Что уже реализовано в консистентном стиле `Stage -> Engine -> Core`.
2. Что закрыто и больше не планируется в этом этапе.
3. Что остаётся следующим шагом (cache boundary simplification).

---

## Current Architecture (Implemented)

### 1. Единый контракт `DatasetSpec`
Зафиксирован и внедрен единый публичный API:
1. `build_map_spec`, `build_normalize_spec`, `build_enrich_spec`, `build_match_spec`, `build_resolve_spec`, `build_sink_spec`.
2. `build_map_stage`, `build_normalize_stage`, `build_enrich_stage`, `build_match_stage`, `build_resolve_stage`.
3. `build_transform_stages` как convenience-агрегатор (`map -> normalize -> enrich`).
4. `build_planning_stages` как convenience-агрегатор (`match -> resolve`).

Итог:
1. Сборка стадий централизована в `DatasetSpec`.
2. Use-case/commands больше не собирают core/rules вручную.

### 2. StageEngine как фасад стадии
Во всех стадиях используется один стиль:
1. Stage получает готовый `*Engine`.
2. `*Engine` скрывает DSL-компиляцию.
3. `*Core` хранит бизнес-логику.
4. Use-case только оркестрирует поток и runtime-параметры.

### 3. BuildOptions в DSL core
Введены и подключены:
1. `BaseDslBuildOptions`.
2. `MapDslBuildOptions`, `NormalizeDslBuildOptions`, `EnrichDslBuildOptions`, `MatchDslBuildOptions`, `ResolveDslBuildOptions`.
3. Merge policy: `defaults -> global -> dataset.stage`.

Источник опций:
1. `datasets/registry.yml`.
2. Это compile-policy, не бизнес-правила датасета.

### 4. DSL core вынесен в `connector/domain/dsl`
Слои больше не завязаны на `domain/transform/dsl/*`.

Итог:
1. DSL-ядро стало shared-компонентом.
2. Готово к повторному использованию вне transform-контура.

---

## Closed Items

Этапы ниже считаются закрытыми:
1. Единый контракт `DatasetSpec` для всех 5 стадий.
2. Перевод match/resolve orchestration на stage-builders.
3. Удаление legacy planning bundle API из production path.
4. Единый паттерн BuildOptions для стадий.
5. Тесты на contract builders и build-options merge.

---

## Stable Rules (Do Not Regress)

### 1. `DatasetSpec` собирает стадии, use-case их только запускает
Нельзя:
1. Возвращаться к ручной сборке matcher/resolver core в use-case/command.

### 2. `*Engine` скрывает DSL
Нельзя:
1. Прокидывать `dsl=...` из `DatasetSpec` в production path.

Допустимо:
1. Оставлять test/migration hooks (`dsl/registry/options overrides`) только для тестов.

### 3. Runtime-параметры остаются вне dataset-конфига
`run_id`, `scope`, `batch_size`, `flush_interval_ms` задаются в runtime/use-case.

### 4. `SinkSpec` остаётся опциональным
Если стадия не требует sink-валидации, `sink_spec` может быть `None`.

---

## Current Inconsistency (Next Target)

### Cache boundary fragmentation
Сейчас cache-доступ разбит на несколько портов/объектов (`cache/identity/pending`) и частично собирается напрямую через SQLite-классы в spec.

Проблемы:
1. Избыточное количество интерфейсов при одной фактической реализации.
2. Дублирующий wiring.
3. Просачивание infra-конкретики в DatasetSpec.

---

## Target Model (Approved)

### 1. One domain cache boundary
Ввести единый порт:
1. `CacheGatewayPort`.

Через него проходят:
1. snapshot/cache операции.
2. identity index операции.
3. pending links операции.

### 2. One runtime cache dependency
`TransformRuntimeDeps`/planning deps должны получать:
1. один `cache_gateway` вместо набора `cache_repo + identity_repo + pending_repo`.

### 3. Composition root owns concrete infra
SQLite-конкретика создаётся только в composition root:
1. `build_cache_gateway(...)`.
2. `DatasetSpec` получает готовый порт.

### 4. Infra internals remain specialized
Внутри `SqliteCacheGateway` допустима делегация в:
1. `SqliteCacheRepository`.
2. `SqliteIdentityRepository`.
3. `SqlitePendingLinksRepository`.

Это внутренняя деталь infra, а не отдельные доменные зависимости.

---

## Cache Migration Plan (Next)

### Iteration A: Introduce unified port
1. Добавить `CacheGatewayPort`.
2. Добавить `SqliteCacheGateway`, реализующий этот порт.
3. Не удалять старые порты до полного переключения (временная совместимость).

### Iteration B: Move wiring to composition root
1. Добавить factory/wiring (`build_cache_gateway`).
2. Убрать из `DatasetSpec` прямое создание `SqliteIdentityRepository`/`SqlitePendingLinksRepository`.
3. Передавать в deps только единый gateway.

### Iteration C: Rewire consumers
1. Перевести matcher/resolver/cache refresh/import apply на `CacheGatewayPort`.
2. Сохранить текущую семантику pending replay/runtime scope.

### Iteration D: Remove legacy
1. Удалить `IdentityRepository`/`PendingLinksRepository` из domain ports.
2. Удалить transitional wiring и лишние imports.
3. Обновить UML/документацию.

### Iteration E: Test gate
1. Контрактные тесты для `CacheGatewayPort`.
2. Regression tests для match/resolve/pending и cache refresh/apply.

---

## Out of Scope (Deferred)

### Settings decomposition
Рефактор `Settings` на профильные секции (`SourceSettings/CacheSettings/...`) остаётся отдельным этапом и в текущую миграцию не включается.

---

## Quick Checklist
Перед merge следующего этапа:
1. Нет прямых SQLite-зависимостей в `DatasetSpec`.
2. Нет ручной сборки core/rules в use-cases.
3. Все стадии строятся через единый style `build_*_stage`.
4. Cache boundary в домене представлена одним портом.
5. Тесты зелёные.

