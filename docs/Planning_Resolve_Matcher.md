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
- `EmployeeMatcher` + `MatchResult` уже реализуют matcher‑логику.
- `GenericPlanner` + `PlanningPolicy` — это resolver‑логика.

## Дополнительные договорённости
1) **MatchKey обязателен после enrich** — matcher принимает только строки с match_key.
2) **RowRef формируется рано** (extract/mapper), чтобы matcher/resolver не вычисляли его.
3) **Fingerprint**: нужен для сравнения дублей внутри source (по умолчанию хеш desired_state).
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
- (опционально) diff policy / ignore_fields

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
