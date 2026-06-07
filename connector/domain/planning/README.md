# connector/domain/planning

## Назначение

Построение плана импорта из результатов трансформационного пайплайна. Plan — это сериализуемый документ, описывающий что именно нужно создать/обновить в целевой системе.

## Файлы

| Файл | Назначение |
|---|---|
| `plan_models.py` | `Plan`, `PlanItem`, `PlanMeta`, `PlanSummary` — иммутабельные dataclass-модели |
| `plan_builder.py` | `PlanBuilder` — собирает `Plan` из потока `TransformResult[ResolvedRow]`; счётчики create/update/skip/failed и callback для failed row diagnostics |
| `record_ref.py` | `RecordRef` — ссылка на запись источника (row_id, line_no) для трейсинга |

## Модель PlanItem

```python
PlanItem:
    row_id: str          # идентификатор строки источника
    line_no: int | None  # номер строки CSV
    op: str              # "create" | "update"
    target_id: str       # ID в целевой системе (для update)
    desired_state: dict  # целевое состояние записи
    changes: dict        # только изменённые поля (для update)
    secret_fields: list  # ССЫЛКИ на vault — не значения
```

## Зависимости

**Зависит от:** `domain/transform/matcher/match_models.py` (`ResolvedRow`), `domain/transform/core/result.py`.  
**Используется:** `usecases/operations/import_plan_builder.py`, `infra/artifacts/plan_writer.py`, `infra/artifacts/plan_reader.py`.

## Важно

`secret_fields` в `PlanItem` — это только имена полей, которые являются секретами. Сами значения хранятся в vault и читаются при apply. В plan.json секреты никогда не пишутся.
