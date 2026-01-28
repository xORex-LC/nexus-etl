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
- resource_id (берётся из existing при MATCHED)
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
- `RESOLVE_MISSING_EXISTING`
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
