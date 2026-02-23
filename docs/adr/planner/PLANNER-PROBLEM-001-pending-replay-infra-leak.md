# PLANNER-PROBLEM-001: Pending replay — разорванная пара сериализации и утечка инфраструктурной логики в ImportPlanService

> **Статус**: Открыта / Решена в PLANNER-DEC-001
> **Дата создания**: 2026-02-23
> **Затронутые компоненты**: `ImportPlanService`, `PendingReplayPort`, `ResolveRuntimePort`, `ResolveUseCase`

---

## 📋 Контекст

После миграции TRANSFORM-DEC-004 (Stage 5) `ImportPlanService` перестал собирать стадии вручную: он получает pre-built `PipelineOrchestrator`, `MatchStage`, `ResolveStage` от команды. Однако в нём остался крупный блок, не относящийся к оркестрации: загрузка и десериализация pending строк из хранилища.

Pending строки — это строки, которые в предыдущем прогоне `import_plan` успешно прошли match, но не смогли быть разрезолвлены (например, менеджер ещё не был обработан). Они сохраняются в SQLite в виде JSON-снапшота `MatchedRow`, чтобы при следующем прогоне пройти только стадию resolve (без повторного прохода через CSV и match).

---

## ⚠️ Проблема

В `import_plan_service.py` обнаружено два связанных нарушения:

**Нарушение 1 — Phantom port: `PendingReplayPort` ≡ `ResolveRuntimePort`**

```python
class PendingReplayPort(ResolveRuntimePort, Protocol):
    """Контракт для replay pending rows в import-plan path."""
    # Ничего не добавляет
```

`PendingReplayPort` является полным алиасом `ResolveRuntimePort` без добавления ни одного метода. При этом `PlanningRuntimePort` уже наследует `ResolveRuntimePort`, то есть `import_plan_service.run()` получает два параметра с пересекающимися возможностями (`pending_replay` и `planning_runtime`), оба указывающих на один объект (`SqliteCacheGateway`) в runtime.

**Нарушение 2 — Пара сериализации разорвана через слои**

```
resolve_core.py (domain):    _serialize_pending_payload()  →  JSON  →  storage
import_plan_service.py (use case):  _deserialize_*()           ←  JSON  ←  storage
```

Сериализация создаётся в `resolve_core.py` (domain). Десериализация (~200 строк) живёт в `import_plan_service.py` (use case layer): `_load_pending_rows()`, `_deserialize_pending_matched_row()`, `_deserialize_match_decision()`, `_deserialize_candidate()`, `_deserialize_source_links()`. Use case знает о формате JSON в хранилище.

**Нарушение 3 — Pending replay — это resolve-concern, а не planning-concern**

Pending строки созданы resolve-стадией (когда link не разрезолвлен) и нужны resolve-стадии (для повторного прохода). Планнер (`ImportPlanService`) не должен знать о их существовании — он просто собирает план из уже разрезолвленных строк.

---

## 🔍 Симптомы

- **`ImportPlanService`** импортирует `json`, `MatchedRow`, `MatchCandidate`, `MatchDecision`, `MatchDecisionStatus`, `Identity`, `RowRef`, `SourceRecord` — чрезмерная связность для оркестратора
- **`PendingReplayPort`** — фантомный тип, не несёт семантической нагрузки, создаёт иллюзию ISP-соответствия
- **`import_plan_service.py`** содержит ~200 строк десериализации, не связанных с его core-задачей (оркестрация transform → match → resolve → plan)
- Конструкция `chain(matched_rows, pending_rows)` в `ImportPlanService` скрывает, что pending — это resolve-input, а не planning-input

---

## 📊 Масштаб проблемы

- **Частота**: Структурная (существует всегда, не зависит от данных)
- **Критичность**: Средняя (функционально работает, но нарушает SRP и расположение логики по слоям)
- **Затронуто**: Команда `import_plan`, `ImportPlanService`, контракт `ResolveRuntimePort`, слой тестирования `ImportPlanService`

---

## 🚫 Почему это проблема?

- `ImportPlanService` знает о JSON-формате persistence layer — нарушение Dependency Rule (use case не должен зависеть от деталей хранилища)
- При изменении формата pending payload придётся менять use case, а не инфраструктуру
- `PendingReplayPort` вводит в заблуждение: создаёт видимость narrow interface, оставаясь fat interface
- `ResolveUseCase` и `ImportPlanService` дублируют обязанности по оркестрации resolve-потока
- Тестирование `ImportPlanService` требует mock-ать JSON-десериализацию, что не является поведением use case

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Десериализация в `SqliteCacheGateway`, новый метод в порте

- **Идея**: `ResolveRuntimePort` получает метод `list_pending_matched_rows(dataset) -> list[TransformResult[MatchedRow]]`. `SqliteCacheGateway` реализует полную десериализацию. `ResolveUseCase.iter_resolved()` принимает опциональный `pending_replay: ResolveRuntimePort | None` и сам делает `chain`.
- **Плюсы**: Чистое разделение слоёв; `ImportPlanService` теряет `pending_replay` параметр и 200 строк кода; пара сериализации замкнута в infra; `PendingReplayPort` удаляется
- **Минусы**: Порт возвращает высокоуровневый доменный тип (`TransformResult`); `ResolveRuntimePort` приобретает осведомлённость о pipeline-типах

### Вариант 2: Выделить `PendingRowCodec` в infra, передавать в `ImportPlanService`

- **Идея**: Отдельный класс/модуль `infra/cache/pending_codec.py` инкапсулирует де/сериализацию; `ImportPlanService` использует его через новый параметр
- **Плюсы**: Локализует формат сериализации в infra без изменения контракта порта
- **Минусы**: `ImportPlanService` всё ещё знает о pending как отдельной сущности; `PendingReplayPort` остаётся или усложняется; оркестрация pending в use case

### Вариант 3: Pending replay как часть `open_match_runtime`

- **Идея**: `open_match_runtime` / `match_runtime` прозрачно appends pending rows к `matched_rows`
- **Плюсы**: Скрывает pending от всех вышестоящих слоёв
- **Минусы**: Смешивает match runtime с replay-семантикой; pending не проходит через match — они already-matched

---

## 🔗 Связанные документы

- [PLANNER-DEC-001](./PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — принятое решение
- `connector/usecases/import_plan_service.py` — основной файл с проблемой
- `connector/domain/ports/cache/roles.py` — `PendingReplayPort`, `ResolveRuntimePort`
- `connector/domain/transform/resolver/resolve_core.py` — `_serialize_pending_payload()`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Проблема обнаружена при ревью `ImportPlanService` после TRANSFORM-DEC-004 Stage 5 |
| 2026-02-23 | Решение принято в PLANNER-DEC-001 |
