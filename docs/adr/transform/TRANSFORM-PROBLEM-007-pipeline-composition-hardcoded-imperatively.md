# TRANSFORM-PROBLEM-007: Состав конвейера задаётся императивно — нет декларативного единого источника истины

> **Статус**: Открыта / Решена в [TRANSFORM-DEC-007](./TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md)
> **Дата создания**: 2026-02-23
> **Затронутые компоненты**: `PipelineContainer`, `AppContainer`, delivery-команды, `PlanningPipeline`

---

## 📋 Контекст

[TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md) переносит знание о составе конвейера `import_plan` из `ImportPlanService` в `PlanningPipeline` (delivery-класс, создаваемый `PipelineContainer`). Это устраняет утечку из use-case слоя, но не решает более глубокий вопрос: **состав каждого сценария по-прежнему жёстко зашит в Python-коде**.

В текущей и целевой (после DEC-006) архитектуре ни одно место не содержит единого декларативного описания "какой сценарий состоит из каких стадий".

---

## ⚠️ Проблема

После реализации DEC-006 каждая delivery-сборка всё равно содержит hardcoded список стадий:

```python
# PlanningPipeline — даже после DEC-006 всё ещё императивно:
class PlanningPipeline:
    def __init__(self, map_stage, normalize_stage, enrich_stage, match_stage, resolve_stage):
        self._transform = PipelineOrchestrator([map_stage, normalize_stage, enrich_stage])
        self._match = match_stage
        self._resolve = resolve_stage

# import_plan.py — даже если использует PlanningPipeline, AppContainer всё равно знает
# о конкретном наборе стадий для этого сценария через providers.Factory(PlanningPipeline, ...)
```

Добавление стадии (например, `validation_stage` между enrich и match) требует:
1. Добавить провайдер в `PipelineContainer`
2. Изменить `PlanningPipeline.__init__` (или аналог для каждого сценария)
3. Изменить `AppContainer.planning_pipeline` провайдер (добавить новый аргумент)

Нет места, где можно сказать: *"для сценария `plan` стадии — вот этот список"* — без изменения кода.

---

## 🔍 Симптомы

- `PlanningPipeline` принимает 5 отдельных stage-аргументов в конструкторе — тесная связь с конкретным составом сценария
- Разные команды (match, normalize, resolve, plan) дублируют перечисление стадий в своих точках сборки
- Нет возможности узнать состав любого сценария без чтения кода соответствующего delivery-модуля
- `PipelineContainer` не может предоставить `transform_segment` как generic "стадии до match" — это понятие не существует нигде декларативно

---

## 📊 Масштаб проблемы

- **Частота**: Структурная (возникает при каждом изменении состава стадий)
- **Критичность**: Средняя (функционально работает; блокирует DSL-эволюцию и routing)
- **Затронуто**: Все CLI-команды при добавлении/изменении стадий; будущие возможности routing и DSL-конфигурации pipeline

---

## 🚫 Почему это проблема?

- **OCP**: добавление стадии требует изменения delivery-класса (`PlanningPipeline`) и DI-провайдеров в `AppContainer` — оба не являются owners состава стадий
- **Нет пути к DSL**: существующий DSL проекта (YAML) управляет transform-правилами, но не структурой самого конвейера. Пока состав задаётся императивно в Python, невозможно перенести эту конфигурацию в YAML
- **Нет пути к routing**: условная маршрутизация строк (`if row.state == X → stage_A, else → stage_B`) требует, чтобы состав и граф конвейера были выражены декларативно — иначе routing нельзя описать без хардкода

---

## 💡 Возможные решения

### Вариант 1: PIPELINE_CHECKPOINTS словарь в AppContainer + PipelineComposer

- **Идея**: Декларативный dict `checkpoint_name → list[stage_name]` как единственное место истины; `PipelineComposer` собирает `PipelineOrchestrator` из stage-фабрик по этому dict-у; `AppContainer` предоставляет composer командам
- **Плюсы**: Единый источник истины; добавление стадии — одна строка в dict; путь к DSL; путь к routing
- **Минусы**: Lifecycle stateful-стадий (match scope cleanup) не выражается простым списком имён — требует отдельной механики

### Вариант 2: DSL (YAML) для конфигурации пайплайна

- **Идея**: Описать checkpoint sequences в YAML по аналогии с transform DSL; загружать при инициализации
- **Плюсы**: Полностью декларативно; переконфигурирование без перекомпиляции
- **Минусы**: Требует решения для lifecycle-хуков; зависит от обобщения `TransformResult` (устранения типизированной привязки row к конкретной стадии); большой scope

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md) — prerequisite (устраняет утечку в use-case); проблема 007 — следующий уровень
- [TRANSFORM-DEC-007](./TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — принятое решение
- [TRANSFORM-PROBLEM-006](./TRANSFORM-PROBLEM-006-pipeline-composition-ownership.md) — предшествующая, более узкая проблема (утечка знания в ImportPlanService)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Проблема сформулирована при обсуждении DEC-006 |
| 2026-02-23 | Решение принято в TRANSFORM-DEC-007 |
