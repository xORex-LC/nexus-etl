# Planning / Resolve / Matcher — договорённости

## Цели
- Упростить добавление новых датасетов.
- Снизить “велосипеды” в planning.
- Чётко разделить ответственность: сопоставление vs решение операции.

## Новая целевая схема (принято)
- **Matcher** и **Resolver** — отдельные этапы с собственными UseCase и отчётами.
- **Plan** больше не ведёт отчёт, он только пишет план для apply.

## Место в пайплайне
Полный ETL:

```
extract → map → normalize → enrich → validate → match → resolve → plan → apply
```

## Ответственность компонентов

### Matcher
- Вход: TransformResult[ValidationRow]
- Задачи:
  - сопоставление по match_key с cache/target
  - сопоставление внутри source (дубли/конфликты)
- Выход: TransformResult[MatchedRow]
- Отчёт: **match report**

### Resolver
- Вход: TransformResult[MatchedRow]
- Задачи:
  - принять решение по операции (create/update/skip/conflict)
  - построить PlanItem (или данные для PlanBuilder)
- Выход: (PlanItem или ResolvedRow)
- Отчёт: **resolve report**

### Plan
- Принимает результат resolver
- Пишет план для apply (артефакт)
- **Отчёта не формирует**

## Взаимосвязь с текущими компонентами
- Matcher/Resolver реализованы как отдельные доменные компоненты.
- Dataset‑специфика задаётся через MatchingRules/ResolveRules в DatasetSpec.

## Дополнительные договорённости
1) **MatchKey обязателен после enrich** — matcher принимает только строки с match_key.
2) **RowRef формируется рано** (extract/mapper), чтобы matcher/resolver не вычисляли его.
3) **Fingerprint**: нужен для сравнения дублей внутри source.
   - алгоритм: `md5(json.dumps(desired_state, sort_keys=True))`
   - используется список `ignored_fields` (dataset‑spec) для исключения мета‑полей
4) **Единый набор статусов** для matcher/resolver (matched/not_found/conflict_*).
5) **Новый stage**: добавить `RESOLVE` или `MATCH` в DiagnosticStage для отчётов.
6) **Validate** оставляет только формат/обязательность; вся логика сопоставления/наличия уходит в matcher/resolver.
7) **Identity можно хранить в TransformResult** (опционально) для упрощения matcher/resolver.
8) **Ошибочные строки не проходят дальше**: matcher/resolver получают только валидные записи,
   а итоговый статус/summary команды считается агрегированно по ошибкам предыдущих стадий
   (enrich/validate), без передачи этих строк в planning.

## Минимум dataset‑специфики
- `identity(row, validation)` — ключ сопоставления
- `desired_state(row)` — каноническое состояние для планирования
- `ignored_fields` — набор полей для fingerprint/diff
- (опционально) diff policy / merge policy / secret_fields_for_op

## Что делать с changes
- **Рекомендация**: оставить вычисление `changes` внутри resolver/planner.
  - Matcher остаётся максимально простым.
  - Resolver принимает matched‑результат и решает update/skip.

## Конфликты внутри source
- Сопоставление по identity внутри набора данных:
  - 1 запись → ок
  - >1 записи:
    - если записи идентичны → можно оставить одну (warning)
    - если различаются → CONFLICT_SOURCE (ошибка, не планировать)

## Статусы сопоставления
- `MATCHED` → найден 1 existing
- `NOT_FOUND` → 0 existing
- `CONFLICT_TARGET` → >1 existing
- `CONFLICT_SOURCE` → дубли внутри source с разным fingerprint

## Минимальные контракты данных

### MatchedRow (минимум)
- row_ref
- identity
- match_status
- desired_state
- existing (если MATCHED)
- fingerprint
- warnings/errors
- source_links (опционально, для cross‑row resolve)

### ResolvedRow (минимум)
- row_ref
- identity
- op (create/update/skip/conflict)
- desired_state
- existing
- target_id (берётся из existing при MATCHED)
- source_ref (опционально)
- warnings/errors
 - changes (для update)

## Коды ошибок (минимум)

### Matcher
- `MATCH_CONFLICT_TARGET`
- `MATCH_CONFLICT_SOURCE`
- `MATCH_IDENTITY_MISSING` (не должен встречаться при соблюдении пайплайна)

### Resolver
- `RESOLVE_CONFLICT`
- `RESOLVE_TARGET_ID_MISSING`
- `RESOLVE_INVALID_STATE`

## Порядок UseCase
```
validate → match → resolve → plan
```
Match/Resolve имеют собственные отчёты; Plan отчёт не формирует.

## Контракт правил matcher/resolver (dataset‑spec)

Ядро matcher/resolver работает через правила (специфика датасета минимальна):

### Matching rules (обязательные)
- `build_identity(row, validation) -> Identity`
- `ignored_fields: set[str]` (для fingerprint/diff)

### In‑batch links (опциональные)
- `build_links(row) -> dict[str, Identity]`
  - пример: `{"manager": Identity(...)}`

### Resolve rules (обязательные)
- `build_desired_state(row) -> dict`
 - `diff_policy(existing, desired_state) -> changes` (можно оставить дефолт)

### Resolve policies (опциональные)
- `merge_policy(existing, desired_state) -> desired_state`
  - если нужно мягкое объединение/игнорирование полей
 - `build_source_ref(identity) -> dict`
 - `secret_fields_for_op(op, desired_state, existing) -> list[str]`

Цель: ядро matcher/resolver не знает структуру датасета, только применяет правила. 

---
## Open questions / observations (post-refactor)

1) **Resolver conflict branch is effectively unused**
   - `Resolver` checks `MatchStatus.CONFLICT_*`, but `Matcher` never sets those statuses.
   - Currently, conflict in matcher returns `row=None` + error, so resolver never sees it.
   - Decide: either emit `MatchedRow` with `match_status=CONFLICT_*` or remove conflict branch in resolver.

2) **Matcher depends on resolve_rules for desired_state**
   - `Matcher` builds `desired_state` via `resolve_rules` to compute fingerprint.
   - This is a mild responsibility leak: matcher now depends on resolve-layer rules.
   - Option: move desired_state builder into `matching_rules` or a shared builder.

3) **ResolveOp.CONFLICT is never produced**
   - `PlanUseCase` checks for `ResolveOp.CONFLICT`, but resolver does not output it.
   - Decide: either remove this case or emit `ResolveOp.CONFLICT` when appropriate.

4) **Fingerprint is computed before merge_policy**
   - If merge_policy mutates desired_state, fingerprint may not reflect final state.
   - Decide if fingerprint should be based on merged desired_state (post-merge) instead.

---
## Мини‑план (pending‑links + re‑resolve)

1) Зафиксировать правила: какие поля считаем link‑полями, какой ключ для resolve, дефолтная политика ошибок/TTL.  
2) Спроектировать служебное хранилище: `identity_index` + `pending_links` (в cache‑DB).  
3) Ввести интерфейс репозитория для identity/pending (под будущий вынос в отдельную БД).  
4) Добавить настройки с дефолтами: `pending_ttl`, `max_attempts`, `sweep_interval`, `on_expire`, `allow_partial`.  
5) Обновить Resolver: пробовать resolve → если нет, писать pending и не пускать в apply; если да — писать resolved в `desired_state`.  
6) Триггеры re‑resolve: на вход новой записи + периодический sweep pending.  
7) Отчётность: фиксировать pending/expired/error.  
8) Тесты: unit на resolver + интеграция с late‑arrival сценарием.

---
## Принятые решения (step 1: rules)

- Link‑поля: любые ссылки на сущности/датасеты (включая междатасетные ссылки).
- Resolve‑ключ: может быть неуникальным (например, ФИО). В таких случаях применяются dedup‑правила из DatasetSpec.
- Конфликт кандидатов: если dedup‑правила не дают однозначного выбора, это `CONFLICT` и запись уходит в pending (далее управляется TTL).
- Dedup‑правила: минимальный декларативный формат (только equality по наборам полей, без кастомных функций).
- TTL по умолчанию: 2 минуты.
- on_expire: `error`.
- allow_partial: `false` (не отправляем в apply без полного resolve).

### Детали реализации для шага 1 (rules)
- В DatasetSpec завести декларацию link‑полей и их resolve‑стратегий:
  - `link_fields`: имя поля, целевой датасет/сущность, источник ключа.
  - `resolve_keys`: приоритетные ключи (например, external_id -> match_key -> name+org).
  - `dedup_rules`: правила выбора при множественных кандидатах (наборы полей для equality, по приоритету).
- Resolver должен уметь:
  - ходить в cache других датасетов (через registry/port),
  - принимать list кандидатов,
  - применять dedup‑правила и возвращать либо resolved_id, либо CONFLICT.

---
## Принятые решения (step 2: storage)

- `source_row_id` генерируется в extract и пишется в мета (пробрасывается через весь pipeline).
- `resolved_id` хранится как `TEXT` для универсальности.
- `identity_index` без `payload` по умолчанию.
  - Dedup‑атрибуты при необходимости подтягиваются из cache по `resolved_id`.
  - Возможна будущая оптимизация: `identity_attrs` (JSON) только для нужных полей из spec.

---
## Принятые решения (step 3: repositories)

- Для `identity_index` и `pending_links` вводим отдельные порты (не переиспользуем CacheRepositoryProtocol).
- Bulk‑операции откладываем, стартуем с одиночных методов.
- В `pending_links` храним `reason` для конфликтов/истечений TTL.

---
## Принятые решения (step 4: settings)

- Настройки кладём в config (ориентируемся на `examples/configs/config_example`).
- Используем глобальные дефолты (без per‑dataset overrides на старте).
- Базовые параметры:
  - `pending_ttl_seconds = 120`
  - `max_attempts = 5` (значение уточним при внедрении)
  - `sweep_interval_seconds = 60`
  - `on_expire = error`
  - `allow_partial = false`

---
## Принятые решения (step 5: resolver behavior)

- `build_desired_state` остаётся как есть, resolve применяется поверх `desired_state`.
- `fingerprint/diff` считаем после resolve (от финального `desired_state`).
- Pending ≠ error: pending отражается отдельным статусом; error ставится только при `expired`/`conflict_unresolved`.

---
## Принятые решения (step 6: re-resolve triggers)

- Триггер 1: после `upsert_identity` проверяем pending по `lookup_key` (та же сущность/датасет) и пытаемся резолвить.
- Триггер 2: периодический `sweep` по `pending_links` (по `sweep_interval_seconds`).
- Триггер 3: при обработке новой входящей записи повторно пытаемся закрыть её собственные pending‑ссылки.

### Опциональные оптимизации (после step 6)

1) **Готовить lookup_key заранее (normalize/enrich)**
   - В `TransformResult.meta` добавляем `link_keys`.
   - На этапе normalize/enrich строим канонический ключ для каждого link‑поля.
   - Resolver берёт `meta.link_keys[field]` без доп. вычислений.

2) **Построить identity_index при refresh cache**
   - На refresh сохраняем `identity_index` (dataset + match_key/external_id → resolved_id).
   - Resolver делает только `find_candidates` по готовому индексу.

3) **In‑batch map**
   - В рамках батча/окна держим `link_key -> row_id` для записей из source.
   - Resolver сначала проверяет in‑batch map, затем identity‑index.

---
## Принятые решения (step 7: reporting)

- В отчёте выделяем отдельный статус для `pending`.
- `expired` и `conflict_unresolved` отражаем как `error` с `reason`.
- Сохраняем `source_row_id`/`field`/`lookup_key` в диагностике для трассировки.

---
## Принятые решения (step 8: tests)

- Unit‑тесты на resolver:
  - resolve успешен (1 кандидат → resolved_id подставлен).
  - конфликт кандидатов → pending + reason.
  - отсутствие кандидатов → pending.
  - expired → error.
- Интеграция:
  - late‑arrival: ссылка сначала pending, затем закрывается после `upsert_identity`.
  - sweep: pending истекают по TTL.

---
## План изменений/переносов (высокоуровневый)

1) **Link‑rules**
   - Модели правил link‑resolve в домене (rules).
   - Расширение DatasetSpec новым контрактом (build_link_rules).
   - Реализация правил для Employees в отдельном файле.

2) **Storage (identity/pending)**
   - Миграция schema: таблицы `identity_index` и `pending_links`.
   - Новые порты: IdentityRepository, PendingLinksRepository.
   - SQLite реализации в infra/cache.

3) **Settings**
   - Добавить настройки TTL/attempts/sweep/on_expire/allow_partial в Settings.
   - Обновить `examples/configs/config_example.yml`.

4) **Deps wiring**
   - Расширить PlanningDependencies (identity_repo, pending_repo, resolver_settings).
   - Прокинуть deps в DatasetSpec и usecases.

5) **Resolver**
   - Resolve link‑полей через identity/pending + dedup.
   - Pending вместо immediate error.
   - Fingerprint/diff после resolve.
   - Удалить/заменить текущую source_links логику.

6) **Identity updates**
   - Обновлять identity_index на refresh cache.
   - Upsert identity после apply (по target_id_map).

7) **Reporting**
   - Статус `pending` в отчётах.
   - `expired/conflict` как error с reason.

8) **Tests**
   - Unit: success/conflict/pending/expired.
   - Integration: late‑arrival + sweep.
