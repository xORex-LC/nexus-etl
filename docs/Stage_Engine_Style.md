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
6. Переход cache runtime на role-based порты в production path (`cache_gateway` в stage/use-case контрактах).
7. Удаление legacy domain cache портов `repository.py`, `identity.py`, `pending_links.py`.

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
Оставить role-based boundary:
1. `CacheAdminPort`
2. `EnrichLookupPort`
3. `MatchRuntimePort`
4. `ResolveRuntimePort`
5. `ApplyRuntimePort`

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

## Role-Based Ports Decision (Refined)

### Why refine the current gateway model
Плоский umbrella-контракт не нужен, потому что:
1. Он быстро становится "толстым" (много методов в одном контракте).
2. Чтение use-case кода хуже: не видно, какая часть cache API реально нужна стадии.
3. При переходе SQLite -> Redis сложнее контролировать минимальные контракты на уровне ролей.

### Chosen direction
Сохраняем один runtime object в DI (`cache_gateway`), но вводим role-based порты:
1. `CacheAdminPort` для refresh/status/clear и snapshot meta.
2. `EnrichLookupPort` для enrich lookup/exists.
3. `MatchRuntimePort` для cache lookup + runtime state + identity index.
4. `ResolveRuntimePort` для identity resolution + pending links lifecycle.
5. `ApplyRuntimePort` для post-apply identity/pending updates.

Важно:
1. В use-case/engine остаётся один аргумент `cache_gateway`.
2. Сужение происходит типами ролей в сигнатурах, а не количеством injected объектов.

### Contract style
Для production path:
1. `SqliteCacheGateway` реализует все role interfaces.
2. Use-cases зависят от "минимального" role port.
3. Umbrella-порт не используется.

---

## Repository Analysis (Current State)

### Already migrated
1. `DatasetSpec` перешел на `cache_gateway` в `build_enrich_deps/build_planning_deps`.
2. `EmployeesSpec` больше не создает `identity/pending` репозитории напрямую.
3. `match/resolve` engines и cores типизированы через role-based контракты.

### Legacy branches still present
1. Внутренние имена полей `SqliteCacheGateway` (`_cache_repo/_identity_repo/_pending_repo`) отражают infra-композицию; это ожидаемая внутренняя деталь.

### Architectural hotspots
1. `connector/delivery/cli/bootstrap.py`: дублирующая сборка gateway.
2. Документация/UML: часть диаграмм может отставать от role-based модели.

---

## Full Migration Plan (Legacy Removal)

### Phase 1: Introduce role ports without behavior change
1. Добавить role interfaces (`CacheAdminPort`, `EnrichLookupPort`, `MatchRuntimePort`, `ResolveRuntimePort`, `ApplyRuntimePort`).
2. Сделать `SqliteCacheGateway` явной реализацией этих ролей.
3. Не менять бизнес-логику стадий.

### Phase 2: Re-type stage/use-case contracts
1. `EnricherEngine/Core` -> `EnrichLookupPort`.
2. `MatchEngine/Core` + `planning_match_runtime` -> `MatchRuntimePort`.
3. `ResolveEngine/Core` + `ResolveUseCase` -> `ResolveRuntimePort`.
4. `ImportApplyService` -> `ApplyRuntimePort`.
5. `cache_refresh/status/clear` use-cases -> `CacheAdminPort`.

### Phase 3: Remove transitional aliases
1. Удалить fallback `deps.cache_repo` из provider registry.
2. Удалить legacy поля/алиасы в deps контейнерах.
3. Нормализовать нейминг параметров (`cache_gateway` во всех сигнатурах).

### Phase 4: Remove legacy ports and adapters
1. Удалить отдельные `IdentityRepository` и `PendingLinksRepository` из domain production path.
2. Удалить `CacheRepositoryProtocol` из use-case contracts, где уже применим role-based API.
3. Оставить только domain-level DTO (`PendingLink`, `PendingRow`, `CacheMeta`, `UpsertResult`) в общем модуле.

### Phase 5: Consolidate composition root
1. Оставить один builder/factory для gateway (без дублирующих helper-ов).
2. Все команды/use-cases получают gateway из одной точки сборки.

### Phase 6: Tests and docs lock
1. Обновить тестовые doubles на role-based контракты.
2. Добавить contract tests для каждого role port.
3. Удалить устаревшие UML/док-референсы на 3-port модель.

## Module-Level Migration Map

### 1. Domain ports
1. `connector/domain/ports/cache/gateway.py`
   - оставить как umbrella boundary на время миграции;
   - целевой шаг: выделить role-based контракты в `connector/domain/ports/cache/roles.py`.
2. `connector/domain/ports/cache/repository.py`
3. `connector/domain/ports/cache/identity.py`
4. `connector/domain/ports/cache/pending_links.py`
   - после переключения production path на role ports -> удалить из runtime-контрактов;
   - допускается временно оставить только DTO/модели, если они переиспользуются.

### 2. Infra cache
1. `connector/infra/cache/gateway.py`
   - единый runtime-адаптер;
   - реализует все role-based контракты (или umbrella + роли в переходный период).
2. `connector/infra/cache/repository.py`
3. `connector/infra/cache/identity_repository.py`
4. `connector/infra/cache/pending_links_repository.py`
   - остаются внутренними деталями gateway (композиция, не domain-deps).

### 3. Composition root and dataset wiring
1. `connector/delivery/cli/bootstrap.py`
2. `connector/usecases/import_plan_service.py`
   - убрать дублирующие `_build_cache_gateway*`;
   - оставить один путь сборки gateway.
3. `connector/datasets/employees/spec.py`
   - не создавать sqlite-классы напрямую;
   - получать уже собранный gateway в deps.

### 4. Stage/use-case contracts
1. `connector/domain/transform/providers/registry.py`
   - удалить fallback на `deps.cache_repo` (legacy bridge).
2. `connector/domain/transform/matcher/match_core.py`
3. `connector/domain/transform/resolver/resolve_core.py`
4. `connector/usecases/cache_refresh_service.py`
5. `connector/usecases/import_apply_service.py`
6. `connector/usecases/import_plan_service.py`
7. `connector/usecases/cache_status_usecase.py`
8. `connector/usecases/cache_clear_usecase.py`
   - перевести сигнатуры на role-based порт(ы);
   - унифицировать naming (`cache_gateway` вместо `cache_repo/identity_repo/pending_repo`).

### 5. Commands layer
1. `connector/delivery/commands/cache_refresh.py`
2. `connector/delivery/commands/cache_clear.py`
3. `connector/delivery/commands/cache_status.py`
4. `connector/delivery/commands/import_apply.py`
5. `connector/delivery/commands/import_plan.py`
   - оставить orchestration-only;
   - не прокидывать отдельные identity/pending зависимости.

## Real Legacy Branches (Observed in Repository)
1. Внутренние имена полей `SqliteCacheGateway` (`_cache_repo/_identity_repo/_pending_repo`) отражают infra-композицию; это не domain-legacy, но часто путается с DI-контрактами.

## Migration Guardrails
1. Не менять бизнес-семантику `pending replay` в процессе контрактной миграции.
2. Не трогать `runtime scope cleanup` в match runtime (`clear_runtime_scope`) до стабилизации role ports.
3. Удалять fallback/legacy только после переключения всех call-sites.
4. Сначала retype контрактов, потом удаление портов/алиасов.
5. Каждую фазу закрывать тестами до следующей (no "big bang" deletion).

## Suggested Order (Concrete)
1. Ввести role-based контракты (без удаления legacy). ✅
2. Перевести stage cores + services на role-based типы. ✅
3. Перевести commands/use-cases naming на `cache_gateway`. ✅
4. Убрать fallback `cache_repo` из provider registry. ✅
5. Удалить legacy ports из production contracts. ✅
6. Убрать дубли builders в composition root. ✅
7. Финально почистить документацию/UML и зафиксировать DoD. ⏳

---

## Migration Risks and Pitfalls

### Risk 1: Hidden dual-contract support
Пока есть fallback (`cache_gateway` + `cache_repo`), легко не заметить старые call-sites.
Mitigation:
1. Ввести временный test guard: forbid `cache_repo` attribute usage в production deps.
2. Удалить fallback отдельным PR после retype.

### Risk 2: Transaction semantics drift
`cache_refresh` и будущие bulk операции завязаны на `transaction()`.
Mitigation:
1. Зафиксировать `transaction` в `CacheAdminPort`.
2. Добавить contract test: nested/rollback expectations для SQLite/Redis adapters.

### Risk 3: Runtime state lifecycle
`match` требует `clear_runtime_scope` в конце run.
Mitigation:
1. Оставить cleanup в `planning_match_runtime` как обязательный.
2. Проверять это интеграционным тестом на repeated runs.

### Risk 4: Pending replay coupling
`resolve` и `import_plan_service` используют pending rows как bridge.
Mitigation:
1. Зафиксировать единый API pending lifecycle в `ResolveRuntimePort`.
2. Не дублировать replay logic в нескольких use-cases.

### Risk 5: Test fixture divergence
Текущие тесты часто используют lightweight deps с `cache_repo`.
Mitigation:
1. Обновить fixture helpers на `cache_gateway` role contracts.
2. Удалить backward-compat shims после миграции тестов.

---

## Definition of Done (Cache Role Migration)
1. Use-case/engine contracts используют только role-based порты. ✅
2. Нет references на `cache_repo/identity_repo/pending_repo` aliases в production path (кроме infra internal composition). ✅
3. `ProviderGateway` не содержит fallback на legacy атрибуты. ✅
4. `bootstrap` имеет единственный путь сборки gateway. ✅
5. Все тесты зелёные, включая contract tests для role ports. ✅
6. UML и docs синхронизированы с новой моделью. ⏳

---

## Cache Migration Status

Текущий актуальный план по cache boundary находится в разделах:
1. `Module-Level Migration Map`
2. `Real Legacy Branches (Observed in Repository)`
3. `Migration Guardrails`
4. `Suggested Order (Concrete)`
5. `Definition of Done (Cache Role Migration)`

Старый поэтапный блок миграции удалён как устаревший, чтобы исключить противоречия.

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
4. Cache boundary в домене представлена role-based контрактами + одним runtime gateway object.
5. Тесты зелёные.
