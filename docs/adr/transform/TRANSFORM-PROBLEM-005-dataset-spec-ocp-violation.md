# TRANSFORM-PROBLEM-005: DatasetSpec — нарушение OCP при добавлении стадий

> **Статус**: Открыта / Решена в [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md)
> **Дата создания**: 2026-02-22
> **Затронутые компоненты**: `DatasetSpec`, `EmployeesSpec`, `StageFactory`, `PipelineContainer`

---

## 📋 Контекст

В [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) принята модульная pipeline-архитектура с Registry Pattern (`StageFactory` + `StageDescriptor`). Добавление новой стадии в `StageFactory` полностью закрыто для модификации: достаточно вызвать `factory.register(StageDescriptor(...))` в delivery layer, не затрагивая ни сам `StageFactory`, ни оркестратор.

Однако `DatasetSpec` — протокол, объявляющий типизированные методы построения DSL-спецификаций стадий — остаётся открытым к изменениям. Для каждой стадии протокол декларирует отдельный метод:

```python
class DatasetSpec(Protocol):
    def build_map_spec(self) -> MappingSpec: ...
    def build_normalize_spec(self) -> NormalizeSpec: ...
    def build_enrich_spec(self) -> EnrichSpec: ...
    def build_match_spec(self) -> MatchSpec: ...
    def build_resolve_spec(self) -> ResolveSpec: ...
    def build_sink_spec(self) -> SinkSpec: ...
    def build_record_source(self, source_has_header: bool) -> Iterable[SourceRecord]: ...
```

При добавлении новой стадии этот набор методов должен расти — что нарушает Open/Closed Principle на уровне протокола.

---

## ⚠️ Проблема

`DatasetSpec` Protocol требует per-stage типизированного метода `build_*_spec()`. Это означает, что добавление новой стадии в pipeline неизбежно влечёт изменение двух файлов протокольного слоя:

1. `DatasetSpec` (протокол) — добавить `build_new_spec() → NewSpec`
2. `EmployeesSpec` (единственная реализация) — реализовать метод

Фактически `DatasetSpec` знает о конкретных типах всех стадий, а не только о generic DSL-интерфейсе. Это DSL-level churn: рост числа стадий линейно растёт количество методов в протоколе.

---

## 🔍 Симптомы

- **Симптом 1**: `DatasetSpec` содержит N методов `build_*_spec()`, где N = числу стадий. Протокол растёт вместе с количеством стадий.
- **Симптом 2**: При добавлении новой стадии (example: `DeduplicateStage`) нужно изменить `DatasetSpec` — protocol change для всех реализаций, не только для добавляемой.
- **Симптом 3**: `PipelineContainer` обращается к конкретным методам (`spec.build_map_spec()`, `spec.build_enrich_spec()`, ...) — связан со структурой протокола.
- **Симптом 4**: Если в будущем появятся датасеты, которые не поддерживают определённые стадии, протокол не позволяет это выразить элегантно.

---

## 📊 Масштаб проблемы

- **Частота**: При каждом добавлении новой стадии
- **Критичность**: Средняя — текущий набор стадий (5 штук) стабилен, новые не ожидаются в ближайшем горизонте
- **Затронуто**: `DatasetSpec`, все его реализации (пока только `EmployeesSpec`), `PipelineContainer` wiring

---

## 🧪 Как воспроизвести

1. Принять решение о добавлении новой стадии `DeduplicateStage` в pipeline
2. Создать `StageDescriptor` для неё в `_build_stage_factory()`
3. Попытаться добавить provider в `PipelineContainer` вида:
   ```python
   dedup_stage = providers.Factory(
       lambda f, spec, ctx: f.create("dedup", spec.build_dedup_spec(), ctx),
       ...
   )
   ```
4. **Ожидаемый результат**: достаточно изменить `_build_stage_factory()` + `PipelineContainer` — `DatasetSpec` не трогаем
5. **Фактический результат**: `spec.build_dedup_spec()` не существует → нужно добавить в `DatasetSpec` и `EmployeesSpec`

---

## 🚫 Почему это проблема?

- Нарушается Open/Closed Principle на уровне протокола: `DatasetSpec` должен быть закрыт для модификаций, когда мы добавляем новые стадии
- `StageFactory` закрыт для модификации (Registry Pattern), но `DatasetSpec` остаётся открытым — архитектурная непоследовательность
- `EmployeesSpec` как хардкод под один датасет всё равно нужно менять, но при переходе на generic YAML-driven реализацию это станет невозможным: YAML-impl не может знать о typed методах для каждого будущего типа стадии
- Со временем, при росте числа стадий (или датасетов с разными наборами стадий), протокол становится раздутым

---

## 💡 Возможные решения

### Вариант A: Сохранить typed build_*_spec() — DSL coupling compromise

- **Идея**: Оставить текущую структуру. `DatasetSpec` продолжает объявлять per-stage методы. Это осознанный компромисс.
- **Плюсы**: Нет усилий на изменение. IDE autocomplete, mypy-типизация.
- **Минусы**: OCP нарушен на уровне протокола. Не работает при generic YAML-driven реализации.

### Вариант B: `build_spec_for(stage_type: str) → object` — generic accessor

- **Идея**: Единственный метод для получения spec по имени стадии. `PipelineContainer` вызывает `spec.build_spec_for("map")` вместо `spec.build_map_spec()`.
- **Плюсы**: Полностью закрывает OCP. Совместим с YAML-driven реализацией. Протокол не растёт.
- **Минусы**: Теряется статическая типизация (возвращает `object`). IDE не подсказывает доступные стадии.

### Вариант C: Sub-protocols per stage

- **Идея**: `class MapSpecProvider(Protocol): def build_map_spec() → MappingSpec: ...` — отдельный протокол на каждую стадию. `PipelineContainer` принимает `MapSpecProvider` вместо `DatasetSpec`.
- **Плюсы**: Полная типизация. OCP закрыт (новая стадия = новый мелкий протокол, старые не меняются). Fine-grained.
- **Минусы**: Взрывной рост числа протоколов. Сложный wiring в `PipelineContainer`. Высокий effort.

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — контекст: Modular Pipeline architecture, где DatasetSpec сужается
- [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md) — принятое решение
- `connector/datasets/spec.py` — `DatasetSpec` протокол
- `connector/datasets/employees/spec.py` — `EmployeesSpec` реализация

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-22 | Проблема выявлена при ревью TRANSFORM-DEC-004 (worklog п.3: DatasetSpec OCP gap) |
| 2026-02-22 | Зафиксирована как осознанный компромисс Phase 1 в DEC-004. Открыта для отдельного решения |
| 2026-02-22 | Решение принято в TRANSFORM-DEC-005 |
