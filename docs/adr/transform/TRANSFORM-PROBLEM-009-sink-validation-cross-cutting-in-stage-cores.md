# TRANSFORM-PROBLEM-009: Sink schema validation — cross-cutting concern внутри всех stage cores

> **Статус**: Открыто (наблюдение)
> **Дата**: 2026-02-24
> **Затронутые компоненты**: `connector/domain/transform/common/sink_schema.py`, все 4 stage cores (mapper, normalizer, enricher, resolver)
> **Обнаружено в ходе**: Аудит RESOLVER-DEC-001 — проверка полноты вынесения инфраструктурных механик

---

## Проблема

Все четыре stage cores (`MapperCore`, `NormalizerCore`, `EnricherCore`, `ResolveCore`) содержат одинаковый паттерн: получают `sink_spec: SinkSpec | None` через конструктор и вызывают функции из `sink_schema.py` для валидации мутированных данных.

Это **единообразный cross-cutting concern**, а не anomaly конкретной стадии.

### Фактическое использование

| Стадия | Функция | Тип валидации | `check_types` | Файл (точка вызова) |
|--------|---------|---------------|---------------|---------------------|
| **Mapper** | `validate_sink_row()` | Full (вся row) | `False` | `mapper_core.py:254-274` |
| **Normalizer** | `validate_sink_row()` / `validate_sink_fields()` | Full или Selective (настраивается через `validate_only_touched_fields`) | `True` | `normalizer_core.py:95-113` |
| **Enricher** | `validate_sink_fields()` | Selective (одно поле перед записью) | `True` | `enricher_core.py:591-599` |
| **Resolver** | `validate_sink_fields()` | Selective (`mutated_fields` после merge+links) | `True` | `resolve_core.py:356-386` |

### Паттерн: guard на границе собственных мутаций

Каждая стадия валидирует именно то, что она мутировала:

- **Mapper**: после применения всех mapping-правил → full validation (required/nullable)
- **Normalizer**: после normalize-правил → full или selective по `touched_fields`
- **Enricher**: перед записью обогащённого значения → selective per-field
- **Resolver**: после merge-policy и link-resolution → selective на `mutated_fields`

### Что создаёт coupling

1. **Все 4 cores зависят от `SinkSpec`** — модель из `transform_dsl`
2. **Все 4 cores зависят от `DslIssue`** — результат `validate_sink_*()`, маппится в `DiagnosticItem`
3. **Каждый core содержит маппинг** `DslIssue → DiagnosticItem` с собственной error policy (`on_error="warn"` у Mapper, stage-specific у остальных)

### Следствия

- Изменение формата `SinkSpec` или `DslIssue` затрагивает все 4 ядра
- Миграция валидационной модели (например, на Pydantic validators) требует правки 4 мест
- Каждый core тестируется с sink_spec setup — дублирование test fixtures
- Core logic смешана с boundary validation: ядро «знает» о схеме целевой системы

### Почему это НЕ блокирующая проблема

- Не блокирует `StageContract` compliance — валидация per-record, внутри `run()`
- Не нарушает декларативность `PIPELINE_CHECKPOINTS`
- Не мешает DI-регистрации
- Паттерн единообразен — не создаёт asymmetry между стадиями

### Почему зафиксировано как наблюдение

Функциональная карта resolver'а ([11.3](../../dev/layers/resolver/functional-capabilities-map.md)) классифицировала это как `Cross-layer leakage, High priority` в контексте одной стадии. При pipeline-wide анализе выяснилось, что это **устоявшийся паттерн всех 4 стадий**, а не специфическая аномалия resolver.

Вынесение из одного core без вынесения из остальных создаст **asymmetry**, а не уменьшит coupling. Правильное решение — pipeline-wide, а не per-stage.

---

## Возможные направления решения

### Вариант A: Validation middleware / decorator

```
StageCore.run()           →  возвращает result + mutated_fields
ValidationDecorator.run() →  вызывает validate_sink_fields(mutated_fields)
                          →  маппит DslIssue → DiagnosticItem
```

**Плюсы**: cores не знают о SinkSpec; единое место маппинга.
**Минусы**: Mapper делает full validation, Enricher — pre-assignment; унификация нетривиальна.

### Вариант B: Post-stage validation hook

Валидация через `PipelineHooks.on_record_complete(stage, record, mutated_fields)`.

**Плюсы**: декларативно, вне cores.
**Минусы**: Enricher валидирует **до** записи (pre-assignment guard), а не после — не ложится в post-hook.

### Вариант C: Оставить как есть (accepted pattern)

Зафиксировать как осознанный выбор: sink validation — это per-stage guard, ближайший к точке мутации.

**Плюсы**: простота; guard валидирует в точке, где мутация ещё может быть отменена.
**Минусы**: coupling остаётся; 4 места маппинга DslIssue → DiagnosticsItem.

---

## Критерий решения

Решение будет принято, когда:
- Появится реальный драйвер (миграция SinkSpec, изменение validation модели, добавление 5+ стадии)
- Или будет сформирована pipeline-wide архитектура middleware/interceptors

До тех пор — accepted pattern, не требующий немедленного action.

---

## Связанные документы

- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — анализ, в ходе которого обнаружена pipeline-wide природа проблемы
- [functional-capabilities-map (resolver)](../../dev/layers/resolver/functional-capabilities-map.md) — раздел 11.3, первоначальная классификация
- `connector/domain/transform/common/sink_schema.py` — общая реализация валидации
