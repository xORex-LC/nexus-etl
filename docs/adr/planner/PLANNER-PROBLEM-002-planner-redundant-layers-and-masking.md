# PLANNER-PROBLEM-002: Планнер выполняет избыточные операции и нарушает границы ответственности

> **Статус**: Открыта / Решена в [PLANNER-DEC-002](./PLANNER-DEC-002-dissolve-planner-layers.md)
> **Дата создания**: 2026-02-23
> **Затронутые компоненты**: `plan_writer.py`, `PlanUseCase`, `ImportPlanService`, `PlanBuilder`

---

## 📋 Контекст

После реализации [PLANNER-DEC-001](./PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) и [TRANSFORM-DEC-006](../transform/TRANSFORM-DEC-006-pipeline-segments-in-container.md) из `ImportPlanService` уходят pending-десериализация и знание о стадиях пайплайна. Остаётся тонкий координатор, вызывающий `PlanUseCase` + `write_plan_file` + logging. В этой упрощённой форме обнаруживаются три самостоятельных нарушения, решаемых комплексно.

---

## ⚠️ Проблема

### Нарушение 1: Мёртвая маскировка в `plan_writer.py`

```python
# connector/infra/artifacts/plan_writer.py
def _mask_sensitive_item(item: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(item))
    return maskSecretsInObject(clone)

masked_items = [_mask_sensitive_item(item) for item in plan_items]
```

К моменту формирования `plan_items` реальные значения секретных полей **уже отсутствуют**: enrich-стадия записывает их в vault и очищает из строки, передавая дальше по конвейеру только список имён (`secret_fields`). `plan_items` содержит имена полей и метаданные, не значения. Вызов `maskSecretsInObject` — мёртвый код: маскировать нечего.

### Нарушение 2: `PlanUseCase` — пустая обёртка без собственной логики

```python
# connector/usecases/plan_usecase.py
class PlanUseCase:
    def run(self, resolved_row_source) -> PlanBuildResult:
        builder = PlanBuilder()
        for resolved in resolved_row_source:
            if resolved.row is None: continue
            if resolved.errors: continue
            if resolved.row.op == ResolveOp.CONFLICT: continue
            builder.add_resolved(resolved.row)
        return builder.build()
```

`PlanUseCase` не имеет зависимостей и не несёт собственной бизнес-логики. Это фильтр-цикл над `PlanBuilder`, который уже живёт в `connector/domain/planning/`. Фильтрация ("не включать ошибки, не включать CONFLICT") — domain rule, принадлежащая `PlanBuilder`. Слой use-case здесь избыточен.

### Нарушение 3: `ImportPlanService` импортирует infra — нарушение направления зависимостей

```python
# connector/usecases/import_plan_service.py
from connector.infra.artifacts.plan_writer import write_plan_file  # ← infra в use-case
from connector.infra.logging.setup import logEvent                  # ← infra в use-case
```

После упрощения `ImportPlanService` сводится к:
```python
plan_result = PlanUseCase().run(iter_ok(resolved_rows))
write_plan_file(plan_result, ...)   # ← infra call
logEvent(logger, ...)               # ← infra call
```

Это delivery-координация (вызов domain + infra + logging), а не use-case логика. use-case слой не должен импортировать infra.

---

## 🔍 Симптомы

- `plan_writer.py` выполняет `json.dumps` + `json.loads` + `maskSecretsInObject` на каждом plan_item при записи — ненужные аллокации и CPU
- `PlanUseCase` — `@dataclass` без полей, `__init__` без аргументов; класс существует только как обёртка
- `ImportPlanService` имеет только один публичный метод, который не содержит бизнес-логики — только координирует вызовы
- `connector/usecases/` импортирует из `connector/infra/` — нарушение hexagonal dependency direction

---

## 📊 Масштаб проблемы

- **Частота**: Структурная (каждый запуск import_plan)
- **Критичность**: Низкая (функционально работает); средняя с точки зрения архитектурной чистоты
- **Затронуто**: `import_plan` команда; читаемость и тестируемость planning слоя

---

## 🚫 Почему это проблема?

- **Dead code** в `plan_writer.py`: маскировка без эффекта создаёт ложное ощущение защиты, усложняет код, нарушает принцип наименьшего удивления
- **SRP**: фильтрационные domain rules ("пропустить ошибки, пропустить CONFLICT") живут в use-case, а не в domain, где им место
- **Dependency inversion**: use-case → infra нарушает hexagonal architecture
- **Лишние слои**: два класса без самостоятельной ответственности усложняют граф зависимостей

---

## 💡 Возможные решения

### Вариант 1: PlanBuilder поглощает фильтр, ImportPlanService растворяется в command handler

- **Идея**: `PlanBuilder.build_from_stream(iterable)` — поглощает фильтр-цикл из `PlanUseCase`; `PlanUseCase` и `ImportPlanService` удаляются; command handler вызывает `PlanBuilder` + `write_plan_file` + logging напрямую; `plan_writer.py` теряет маскировку
- **Плюсы**: Чистые слои; domain rules в domain; infra вызывается из delivery; no dead code
- **Минусы**: Command handler берёт больше строк — но это его законная роль (delivery coordination)

### Вариант 2: Оставить ImportPlanService, добавить порт для write_plan_file

- **Идея**: `PlanArtifactPort` абстрагирует запись; `ImportPlanService` остаётся как координатор через порт
- **Плюсы**: Чистая hexagonal форма
- **Минусы**: Порт с одной реализацией без предвидимых альтернатив — преждевременная абстракция; `ImportPlanService` всё равно пустой

---

## 🔗 Связанные документы

- [PLANNER-DEC-002](./PLANNER-DEC-002-dissolve-planner-layers.md) — принятое решение
- [PLANNER-DEC-001](./PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — prerequisite (реализуется совместно)
- [TRANSFORM-DEC-006](../transform/TRANSFORM-DEC-006-pipeline-segments-in-container.md) — prerequisite (PlanningPipeline убирает stage-знание из планнера)
- `connector/domain/planning/plan_builder.py` — целевой владелец domain rules
- `connector/infra/artifacts/plan_writer.py` — упрощается (убирается маскировка)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Проблема обнаружена при анализе остаточных нарушений после PLANNER-DEC-001 |
| 2026-02-23 | Решение принято в PLANNER-DEC-002 |
