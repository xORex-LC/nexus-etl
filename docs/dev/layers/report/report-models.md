# Report Models — Event-Driven Domain и Policy Framework

> **Event-driven telemetry**: pipeline stages emit frozen `ReportEvent` в `IReportSink`; `InMemoryReportContext` выполняет streaming-агрегацию с bounded item sampling и выдаёт immutable `ReportEnvelope` snapshots через `ReportAssembler`.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🔖 Schema v2 контракт](#-schema-v2-контракт)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
  - [ReportEnvelope — корневой объект](#reportenvelope--корневой-объект)
  - [ReportMeta — метаданные запуска](#reportmeta--метаданные-запуска)
  - [ReportSummary — агрегированная статистика](#reportsummary--агрегированная-статистика)
  - [ReportDiagnostic — атомарная диагностика](#reportdiagnostic--атомарная-диагностика)
  - [ReportItem — результат по одной записи](#reportitem--результат-по-одной-записи)
  - [RowRef — ссылка на исходную строку](#rowref--ссылка-на-исходную-строку)
- [📊 Каталог событий (ReportEvent)](#-каталог-событий-reportevent)
  - [Обзор иерархии](#обзор-иерархии)
  - [Meta-события](#meta-события)
  - [Context-события](#context-события)
  - [Ops-события](#ops-события)
  - [Row-события](#row-события)
  - [Status-события](#status-события)
  - [Activity-события](#activity-события)
- [📊 InMemoryReportContext — streaming агрегация](#-inmemoryreportcontext--streaming-агрегация)
  - [Конструктор](#конструктор)
  - [append() — dispatch событий](#append--dispatch-событий)
  - [_apply_add_item() — авто-агрегация row-item](#_apply_add_item--авто-агрегация-row-item)
  - [_derive_status() — вывод итогового статуса](#_derive_status--вывод-итогового-статуса)
  - [Snapshot-методы](#snapshot-методы)
- [📊 Sink Layer — единая точка записи](#-sink-layer--единая-точка-записи)
- [📊 ReportAssembler — сборка финального отчёта](#-reportassembler--сборка-финального-отчёта)
- [📊 Policy Framework — capability-based детализация](#-policy-framework--capability-based-детализация)
  - [ReportPolicyProfile](#reportpolicyprofile)
  - [ReportPolicyCapabilities](#reportpolicycapabilities)
  - [Матрица профилей](#матрица-профилей)
  - [ReportPolicy — resolver-методы](#reportpolicy--resolver-методы)
- [📊 Typed Contracts — ReportContextKey, ReportOpKey](#-typed-contracts--reportcontextkey-reportopkey)
- [📊 Diagnostics — конвертация DiagnosticItem → ReportDiagnostic](#-diagnostics--конвертация-diagnosticitem--reportdiagnostic)
- [📊 Legacy ReportCollector](#-legacy-reportcollector)
- [🔄 Context-пространство имён](#-context-пространство-имён)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Определить event-driven доменную модель report layer — типы данных, события, scoped execution context, policy-контракт и assembler для формирования immutable `ReportEnvelope`.

**Ключевая ответственность**:
- Определить все доменные типы данных отчёта: `ReportEnvelope`, `ReportMeta`, `ReportSummary`, `ReportDiagnostic`, `ReportItem`.
- Определить типизированные immutable-события (`ReportEvent` и подклассы) для event-driven ingestion.
- Реализовать `InMemoryReportContext` — command-scoped контекст с streaming-агрегацией и bounded item sampling.
- Предоставить `IReportSink` / `IActivitySink` — единую точку записи событий для продюсеров.
- Реализовать `ReportAssembler` — сборку финального `ReportEnvelope` из контекста через `IReportEnricher`.
- Определить `ReportPolicy` — capability-based контракт детализации отчёта с профилями `minimal` / `standard` / `debug`.
- Предоставить typed contracts для top-level namespace-ключей: `ReportContextKey`, `ReportOpKey`, `ReportItemStatus`.

**Расположение в кодовой базе**:
- `connector/domain/reporting/models.py` — все dataclass-модели
- `connector/domain/reporting/events.py` — typed-события
- `connector/domain/reporting/context.py` — `IReportContext`, `InMemoryReportContext`, `asdict_envelope()`
- `connector/domain/reporting/sink.py` — `IReportSink`, `IActivitySink`, `ReportSink`, Null-реализации
- `connector/domain/reporting/assembler.py` — `IReportEnricher`, `CompositeReportEnricher`, `ReportAssembler`
- `connector/domain/reporting/policy.py` — `ReportPolicy`, `ReportPolicyCapabilities`, `ReportPolicyProfile`
- `connector/domain/reporting/policy_matrix.py` — декларативная матрица профилей
- `connector/domain/reporting/contracts.py` — `ReportItemStatus`, `ReportContextKey`, `ReportOpKey`, normalizers
- `connector/domain/reporting/diagnostics.py` — `to_report_diagnostics()`, `split_report_diagnostics()`
- `connector/domain/reporting/collector.py` — legacy `ReportCollector` (совместимость)
- `connector/domain/models.py` — `RowRef`, `DiagnosticItem`, `DiagnosticStage`

---

## 🔖 Schema v2 контракт

Начиная с `REPORT-DEC-007` report layer работает по **schema v2**:

- `meta.schema_version = "2.0"` (breaking, dual v1/v2 сериализации нет).
- `ReportItem.status`: только `OK | FAILED | SKIPPED` (typed `ReportItemStatus` enum).
- `ReportSummary.rows_skipped`: отдельный счётчик skip-фактов.
- `RowRef.line_no: int | None`: `None` сохраняется как есть, coercion `None → 0` запрещён.
- `meta.items_truncated = true`: выставляется при любом непомещённом `store=True` item (независимо от статуса).
- top-level namespaces: `context` и `summary.ops` используют typed contracts (`ReportContextKey`, `ReportOpKey`), без magic string на уровне API.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/domain/reporting/
├── __init__.py            # Публичный API: реэкспорт ключевых абстракций
├── models.py              # ReportEnvelope, ReportMeta, ReportSummary, ReportDiagnostic, ReportItem
├── events.py              # ReportEvent и 12 typed-подклассов (frozen dataclass)
├── context.py             # IReportContext (Protocol), InMemoryReportContext, asdict_envelope()
├── sink.py                # IReportSink, IActivitySink, ReportSink, NullReportSink, NullActivitySink
├── assembler.py           # IReportEnricher, CompositeReportEnricher, ReportAssembler
├── contracts.py           # ReportItemStatus, ReportContextKey, ReportOpKey, normalizers
├── policy.py              # ReportPolicy, ReportPolicyCapabilities, ReportPolicyProfile
├── policy_matrix.py       # REPORT_POLICY_PROFILE_MATRIX (декларативная матрица)
├── diagnostics.py         # to_report_diagnostics(), split_report_diagnostics()
├── collector.py           # ReportCollector (legacy compatibility)
└── adapters/              # Stage-level адаптеры → см. report-pipeline.md
    ├── __init__.py
    ├── stage_result_reporter.py
    ├── stats_accumulator.py
    ├── result_policy.py
    ├── payload_sanitizer.py
    └── strategies.py
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Report Layer Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml) | Структура domain-моделей, events, context, sink, assembler |
| Sequence | [Report Layer Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml) | Поток событий от продюсера до JSON-артефакта |

### 🎭 Применённые паттерны

#### Паттерн 1: Event Sourcing Lite (Streaming Aggregation)

**Где применяется**: Все записи в отчёт идут через immutable `ReportEvent` → `IReportSink.emit()` → `InMemoryReportContext.append()`.

**Реализация в коде**:
- **События**: 12 frozen dataclass в `connector/domain/reporting/events.py`
- **Контекст**: `InMemoryReportContext.append()` в `connector/domain/reporting/context.py`

**Пример использования**:
```python
sink.emit(AddItemEvent(status=ReportItemStatus.FAILED, row_ref=row_ref, errors=errors))
sink.emit(SetContextEvent(name=ReportContextKey.NORMALIZE, value=stats.to_context_payload(...)))
```

**Зачем**: В отличие от классического Event Sourcing, raw row-events не хранятся — контекст агрегирует счётчики на лету и сохраняет только bounded sample items. Это обеспечивает единый ingestion API без unbounded memory роста.

#### Паттерн 2: Snapshot Isolation

**Где применяется**: Все snapshot-методы `InMemoryReportContext` и `ReportAssembler.assemble()`.

**Реализация в коде**:
- `InMemoryReportContext.snapshot()` → `deepcopy()` всех полей
- `ReportAssembler.assemble()` → `context.snapshot()` + enricher

**Зачем**: Гарантия, что полученный `ReportEnvelope` не мутируется при продолжении записи событий или при внешнем доступе.

#### Паттерн 3: Null Object

**Где применяется**: `NullReportSink`, `NullActivitySink` для runtime-сценариев без отчёта.

**Реализация в коде**: `connector/domain/reporting/sink.py`

**Зачем**: Usecases и handlers не проверяют `if sink is not None` — всегда вызывают `sink.emit(...)`.

#### Паттерн 4: Composite (Enricher Chain)

**Где применяется**: `CompositeReportEnricher` — цепочка `IReportEnricher` с детерминированным порядком.

**Реализация в коде**: `connector/domain/reporting/assembler.py`

**Зачем**: Расширяемость: новые enrichers добавляются без изменения assembler.

#### Паттерн 5: Capability-based Policy

**Где применяется**: `ReportPolicy` с `ReportPolicyCapabilities` — 7 boolean-флагов определяют детализацию отчёта.

**Реализация в коде**: `connector/domain/reporting/policy.py`, `connector/domain/reporting/policy_matrix.py`

**Зачем**: Разделение profile presets и runtime resolver-логики. Стадии и адаптеры запрашивают capability через resolver-методы, не знают о конкретном профиле.

### Диаграмма зависимостей

```
contracts.py ──┐
               ├──→ models.py ──→ events.py ──→ context.py ──→ sink.py
               │                                   │
policy_matrix.py → policy.py                  assembler.py
               │                                   │
diagnostics.py ┘               adapters/ ──────────┘ (см. report-pipeline.md)
```

---

## 🔑 Ключевые абстракции

| Абстракция | Файл | Тип | Назначение |
|------------|------|-----|-----------|
| `IReportContext` | `context.py` | Protocol | Контракт event-driven контекста с append + snapshots |
| `InMemoryReportContext` | `context.py` | Class | Command-scoped реализация с streaming-агрегацией |
| `IReportSink` | `sink.py` | Protocol | Единая публичная точка записи событий (`emit(event)`) |
| `IActivitySink` | `sink.py` | Protocol | Фасад для подсистемной телеметрии (`emit_activity(name, payload)`) |
| `ReportSink` | `sink.py` | Class | Делегирует события в `IReportContext.append()` |
| `IReportEnricher` | `assembler.py` | Protocol | Контракт enrich-компонента для финального envelope |
| `ReportAssembler` | `assembler.py` | Class | Snapshot + enricher chain → `ReportEnvelope` |
| `ReportPolicy` | `policy.py` | Frozen DC | Profile + capabilities + resolver-методы |

---

## 🗂️ Модели данных

### ReportEnvelope — корневой объект

```python
@dataclass
class ReportEnvelope:
    status: str                          # "SUCCESS" | "PARTIAL" | "FAILED"
    meta: ReportMeta                     # метаданные запуска
    summary: ReportSummary               # агрегированные счётчики
    items: list[ReportItem]              # bounded sample row-level результатов
    context: dict[str, Any] = {}         # namespaced context-блоки (ReportContextKey)
```

### ReportMeta — метаданные запуска

```python
@dataclass
class ReportMeta:
    run_id: str                          # UUID запуска
    dataset: str | None                  # имя dataset (None для dataset-agnostic команд)
    command: str                         # имя CLI-команды
    started_at: str                      # ISO timestamp начала
    schema_version: Literal["2.0"] = "2.0"
    finished_at: str | None = None       # ISO timestamp завершения
    duration_ms: int | None = None       # длительность выполнения
    items_limit: int | None = None       # макс. число хранимых items
    items_truncated: bool = False        # True если items усечены
    app_version: str | None = None       # версия приложения
    git_rev: str | None = None           # git revision
```

### ReportSummary — агрегированная статистика

```python
@dataclass
class ReportSummary:
    rows_total: int = 0                  # всего обработано
    rows_passed: int = 0                 # прошло (OK)
    rows_blocked: int = 0                # заблокировано (FAILED)
    rows_skipped: int = 0                # пропущено (SKIPPED)
    rows_with_warnings: int = 0          # с предупреждениями
    errors_total: int = 0                # суммарно ошибок
    warnings_total: int = 0              # суммарно предупреждений
    by_stage: dict[str, dict[str, int]] = {}  # ошибки/предупреждения по стадиям
    ops: dict[str, dict[str, int]] = {}       # op-счётчики (create, update, skip...)
```

`by_stage` заполняется автоматически при подсчёте диагностик. Формат: `{"NORMALIZE": {"errors_total": 3, "warnings_total": 1}}`.

`ops` заполняется через `AddOpEvent` / `MergeOpFieldsEvent`. Ключи — `ReportOpKey`.

### ReportDiagnostic — атомарная диагностика

```python
@dataclass(frozen=True)
class ReportDiagnostic:
    severity: str                        # "error" | "warning"
    stage: DiagnosticStage               # стадия, породившая ошибку
    code: str                            # код ошибки из ErrorCatalog
    field: str | None                    # поле, к которому относится
    message: str                         # человекочитаемое описание
    rule: str | None = None              # правило валидации (опционально)
    details: dict[str, Any] | None = None  # доп. контекст
```

### ReportItem — результат по одной записи

```python
@dataclass
class ReportItem:
    status: ReportItemStatus             # OK | FAILED | SKIPPED
    row_ref: RowRef | None = None        # ссылка на исходную строку
    payload: Mapping[str, Any] | None = None   # данные строки (masked)
    diagnostics: list[ReportDiagnostic] = []   # ошибки + предупреждения
    meta: dict[str, Any] = {}            # stage-specific метаданные
```

### RowRef — ссылка на исходную строку

```python
@dataclass(frozen=True)
class RowRef:
    line_no: int | None                  # номер строки (None = unknown, НЕ 0)
    source: str | None = None            # имя файла/источника
```

> **Schema v2**: `line_no: int | None` — `None` сохраняется как есть, coercion `None → 0` запрещён.

---

## 📊 Каталог событий (ReportEvent)

### Обзор иерархии

Все события — immutable frozen dataclass, наследуют от `ReportEvent`:

| Событие | Группа | Назначение |
|---------|--------|-----------|
| `SetMetaEvent` | Meta | Обновление полей `ReportMeta` |
| `FinishEvent` | Meta | Финализация: timestamps + duration + derive status |
| `SetContextEvent` | Context | Установка namespaced context-блока |
| `AddOpEvent` | Ops | Инкремент op-счётчиков (ok/failed/count) |
| `MergeOpFieldsEvent` | Ops | Merge произвольных полей в ops[name] |
| `AddItemEvent` | Row | Добавление row-level item + диагностики |
| `SetRowCountersEvent` | Row | Pre-aggregated row counters (compat bridge) |
| `SetStatusEvent` | Status | Явная фиксация итогового статуса |
| `SetItemsTruncatedEvent` | Status | Явная фиксация items_truncated |
| `EnsureErrorsTotalAtLeastEvent` | Status | Гарантия минимального errors_total |
| `ActivityMetricEvent` | Activity | Подсистемная телеметрия через IActivitySink |

### Meta-события

**SetMetaEvent** — патч полей `ReportMeta` (only non-None fields обновляются):

```python
@dataclass(frozen=True)
class SetMetaEvent(ReportEvent):
    dataset: str | None = None
    items_limit: int | None = None
    app_version: str | None = None
    git_rev: str | None = None
```

**FinishEvent** — финализация отчёта:

```python
@dataclass(frozen=True)
class FinishEvent(ReportEvent):
    finished_at: str | None = None   # ISO timestamp или getNowIso()
    duration_ms: int | None = None
```

При обработке: устанавливает timestamps и, если `_status` ещё `None`, вызывает `_derive_status()`.

### Context-события

**SetContextEvent** — установка namespaced context-блока (deep-copy):

```python
@dataclass(frozen=True)
class SetContextEvent(ReportEvent):
    name: ReportContextKey | str
    value: dict[str, Any]
```

### Ops-события

**AddOpEvent** — инкремент стандартных op-счётчиков:

```python
@dataclass(frozen=True)
class AddOpEvent(ReportEvent):
    name: ReportOpKey | str
    ok: int = 0
    failed: int = 0
    count: int = 0
```

**MergeOpFieldsEvent** — merge произвольных полей в `summary.ops[name]`:

```python
@dataclass(frozen=True)
class MergeOpFieldsEvent(ReportEvent):
    name: ReportOpKey | str
    values: Mapping[str, int]
```

### Row-события

**AddItemEvent** — ключевое событие, добавляющее row-level item:

```python
@dataclass(frozen=True)
class AddItemEvent(ReportEvent):
    status: ReportItemStatus | str
    row_ref: RowRef | None = None
    payload: Mapping[str, Any] | None = None
    errors: tuple[ReportDiagnostic, ...] = ()
    warnings: tuple[ReportDiagnostic, ...] = ()
    meta: dict[str, Any] = {}
    store: bool = True                # сохранять ли item в bounded sample
    preaggregated: bool = False       # True = row counters НЕ инкрементируются
```

`preaggregated=True` используется `ApplyReportPresenter`, когда row counters уже установлены через `SetRowCountersEvent`.

**SetRowCountersEvent** — pre-aggregated row counters (compat bridge для apply):

```python
@dataclass(frozen=True)
class SetRowCountersEvent(ReportEvent):
    rows_total: int
    rows_passed: int
    rows_blocked: int
    rows_with_warnings: int
    rows_skipped: int = 0
```

### Status-события

**SetStatusEvent** — явная фиксация итогового статуса (перекрывает `_derive_status()`):

```python
@dataclass(frozen=True)
class SetStatusEvent(ReportEvent):
    status: str | None    # "SUCCESS" | "PARTIAL" | "FAILED" | None
```

**SetItemsTruncatedEvent** — фиксация флага truncation:

```python
@dataclass(frozen=True)
class SetItemsTruncatedEvent(ReportEvent):
    value: bool = True
```

**EnsureErrorsTotalAtLeastEvent** — enforce минимума errors_total (используется ApplyReportPresenter при truncated outcomes с ошибками):

```python
@dataclass(frozen=True)
class EnsureErrorsTotalAtLeastEvent(ReportEvent):
    value: int
```

### Activity-события

**ActivityMetricEvent** — фасад-событие для подсистемной телеметрии:

```python
@dataclass(frozen=True)
class ActivityMetricEvent(ReportEvent):
    name: str                        # имя подсистемы
    payload: Mapping[str, Any]       # произвольные метрики
```

Обрабатывается контекстом: `context["stats"][name] = payload`.

---

## 📊 InMemoryReportContext — streaming агрегация

### Конструктор

```python
InMemoryReportContext(*, run_id: str, command: str, started_at: str | None = None)
```

Создаёт пустой `ReportMeta` + `ReportSummary` + пустые `items` и `context`. `started_at` по умолчанию — текущее время.

### append() — dispatch событий

Диспетчеризация по типу события через `isinstance`-цепочку:

| Тип события | Действие |
|------------|---------|
| `SetMetaEvent` | Патч non-None полей `_meta` |
| `SetContextEvent` | `_context[normalize_context_key(name)] = deepcopy(value)` |
| `AddOpEvent` | `_summary.ops[name][ok/failed/count] += delta` |
| `MergeOpFieldsEvent` | Merge полей в `_summary.ops[name]` |
| `SetRowCountersEvent` | Перезаписать все row-счётчики `_summary` |
| `AddItemEvent` | `_apply_add_item()` — см. ниже |
| `SetItemsTruncatedEvent` | `_meta.items_truncated = value` |
| `EnsureErrorsTotalAtLeastEvent` | `max(current, value)` |
| `SetStatusEvent` | `_status = status` |
| `FinishEvent` | Set timestamps + derive status if None |
| `ActivityMetricEvent` | `_context["stats"][name] = payload` |

Неизвестный тип → `TypeError`.

### _apply_add_item() — авто-агрегация row-item

Алгоритм обработки `AddItemEvent`:

1. Нормализовать `status` через `normalize_item_status()`.
2. Если `preaggregated=False`:
   - `rows_total += 1`
   - `FAILED` → `rows_blocked += 1`
   - `OK` → `rows_passed += 1`
   - `SKIPPED` → `rows_skipped += 1`
   - Если есть warnings → `rows_with_warnings += 1`
3. Подсчитать диагностики: `errors_total += len(errors)`, `warnings_total += len(warnings)`, `by_stage[stage][field] += 1`.
4. Если `store=True` и `len(items) < items_limit` → append `ReportItem`.
5. Если `store=True` и лимит превышен → `items_truncated = True`.

### _derive_status() — вывод итогового статуса

Формула на основе row-счётчиков:

| Условие | Статус |
|---------|--------|
| `rows_blocked == 0` | `SUCCESS` |
| `rows_blocked > 0 AND rows_passed > 0` | `PARTIAL` |
| Иначе | `FAILED` |

Вызывается при `FinishEvent`, если `_status` ещё `None`. Может быть перекрыт явным `SetStatusEvent` до финализации.

### Snapshot-методы

Все возвращают `deepcopy()` — изоляция от продолжающейся записи:

| Метод | Возвращает |
|-------|-----------|
| `snapshot()` | `ReportEnvelope` (полный snapshot) |
| `meta_snapshot()` | `ReportMeta` |
| `summary_snapshot()` | `ReportSummary` |
| `items_snapshot()` | `list[ReportItem]` |
| `context_snapshot()` | `dict[str, Any]` |
| `status_snapshot()` | `str | None` |

---

## 📊 Sink Layer — единая точка записи

```
Продюсер (UseCase / Handler / Adapter)
    │
    ├─ sink.emit(ReportEvent)          # IReportSink — typed events
    └─ sink.emit_activity(name, payload) # IActivitySink — subsystem metrics
          │
          ▼
    ReportSink._context.append(event)  # делегация в InMemoryReportContext
```

| Класс | Протокол | Назначение |
|-------|----------|-----------|
| `IReportSink` | Protocol | `emit(event: ReportEvent)` — единая точка записи |
| `IActivitySink` | Protocol | `emit_activity(name, payload)` — фасад для подсистем |
| `ReportSink` | Impl | Делегирует оба метода в `IReportContext.append()` |
| `NullReportSink` | Impl | No-op для `run_without_report()` |
| `NullActivitySink` | Impl | No-op для подсистем без tracing |

`ReportSink` реализует оба протокола: `IReportSink` и `IActivitySink`. Метод `emit_activity()` оборачивает в `ActivityMetricEvent` и вызывает `emit()`.

---

## 📊 ReportAssembler — сборка финального отчёта

```python
class ReportAssembler:
    def __init__(self, *, context: IReportContext, enricher: IReportEnricher | None = None): ...
    def assemble(self) -> ReportEnvelope: ...
```

Алгоритм `assemble()`:
1. `envelope = context.snapshot()` — immutable deep copy.
2. `enricher.enrich(envelope)` — применить цепочку enrichers.
3. Вернуть `envelope`.

**CompositeReportEnricher** — детерминированная цепочка:

```python
class CompositeReportEnricher(IReportEnricher):
    def __init__(self, enrichers: Iterable[IReportEnricher] | None = None): ...
    def enrich(self, envelope: ReportEnvelope) -> None:
        for enricher in self._enrichers:
            enricher.enrich(envelope)
```

**IReportEnricher** — контракт:

```python
class IReportEnricher(Protocol):
    def enrich(self, envelope: ReportEnvelope) -> None: ...
```

Enricher мутирует envelope in-place (envelope уже snapshot, не разделяемая ссылка).

---

## 📊 Policy Framework — capability-based детализация

### ReportPolicyProfile

```python
class ReportPolicyProfile(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    DEBUG = "debug"
```

### ReportPolicyCapabilities

```python
@dataclass(frozen=True)
class ReportPolicyCapabilities:
    include_ok_items: bool               # хранить OK-items в report
    include_failed_items: bool           # хранить FAILED-items
    include_skipped_items: bool          # хранить SKIPPED-items
    include_payload_masked: bool         # включать masked payload
    include_upstream_diagnostics: bool   # включать upstream-диагностики в meta
    include_subsystem_metrics: bool      # включать подсистемные метрики
    include_runtime_secondary_as_items: bool  # secondary runtime errors как items
```

### Матрица профилей

| Capability | minimal | standard | debug |
|-----------|---------|----------|-------|
| `include_ok_items` | False | True | True |
| `include_failed_items` | True | True | True |
| `include_skipped_items` | False | True | True |
| `include_payload_masked` | False | True | True |
| `include_upstream_diagnostics` | False | False | True |
| `include_subsystem_metrics` | False | True | True |
| `include_runtime_secondary_as_items` | True | True | True |

Матрица хранится в `connector/domain/reporting/policy_matrix.py`.

### ReportPolicy — resolver-методы

```python
@dataclass(frozen=True)
class ReportPolicy:
    profile: ReportPolicyProfile
    capabilities: ReportPolicyCapabilities
```

**Factory-методы**: `minimal()`, `standard()`, `debug()`, `from_profile(profile)`, `from_context(value)`.

**Resolver-методы** (capability AND runtime override):

| Метод | Формула |
|-------|--------|
| `resolve_include_ok_items(cli_flag)` | `capabilities.include_ok_items AND cli_flag` |
| `resolve_include_skipped_items(cli_flag)` | `capabilities.include_skipped_items AND cli_flag` |
| `resolve_include_upstream_diagnostics(requested)` | `capabilities.include_upstream_diagnostics AND requested` |

**resolve_report_policy()** — утилита для внешнего слоя: `report_policy → policy_context → standard`.

---

## 📊 Typed Contracts — ReportContextKey, ReportOpKey

### ReportContextKey (str Enum)

| Ключ | Значение | Кто устанавливает |
|------|----------|------------------|
| `CONFIG` | `"config"` | Runtime orchestrator |
| `INPUT` | `"input"` | Runtime orchestrator |
| `RUNTIME` | `"runtime"` | Runtime orchestrator (finalize) |
| `REPORT_POLICY` | `"report_policy"` | Runtime orchestrator |
| `STATS` | `"stats"` | ActivityMetricEvent / IActivitySink |
| `DICTIONARY` | `"dictionary"` | Command handler (attach_dictionary_report_snapshot) |
| `TARGET_RUNTIME` | `"target_runtime"` | Command handler |
| `VAULT_ROLLOUT` | `"vault_rollout"` | Command handler |
| `APPLY` | `"apply"` | ApplyReportPresenter |
| `APPLY_TARGET` | `"apply_target"` | Command handler |
| `CACHE_STATUS` | `"cache_status"` | Cache commands |
| `CACHE_CLEAR` | `"cache_clear"` | Cache commands |
| `CACHE_REFRESH` | `"cache_refresh"` | Cache commands |
| `MAPPING` | `"mapping"` | StageResultReporter (publish_context) |
| `NORMALIZE` | `"normalize"` | StageResultReporter (publish_context) |
| `ENRICH` | `"enrich"` | StageResultReporter (publish_context) |
| `MATCH` | `"match"` | StageResultReporter (publish_context) |
| `RESOLVE` | `"resolve"` | StageResultReporter (publish_context) |

### ReportOpKey (str Enum)

| Ключ | Значение | Кто устанавливает |
|------|----------|------------------|
| `CREATE` | `"create"` | ApplyReportPresenter |
| `UPDATE` | `"update"` | ApplyReportPresenter |
| `SKIP` | `"skip"` | ApplyReportPresenter |
| `PLAN` | `"plan"` | ApplyReportPresenter (MergeOpFieldsEvent) |
| `APPLY_FAILED` | `"apply_failed"` | ApplyReportPresenter |
| `CACHE_REFRESH` | `"cache_refresh"` | Cache commands |
| `RESOLVE_EXPIRED` | `"resolve_expired"` | ResolveUseCase |
| `RESOLVE_MAX_ATTEMPTS` | `"resolve_max_attempts"` | ResolveUseCase |
| `RESOLVE_PENDING` | `"resolve_pending"` | ResolveUseCase |

### Normalizer-функции

- `normalize_context_key(name)` — `ReportContextKey | str → str`; пустая строка → `ValueError`.
- `normalize_op_key(name)` — `ReportOpKey | str → str`; пустая строка → `ValueError`.
- `normalize_item_status(status)` — `ReportItemStatus | str → ReportItemStatus`; compat bridge: `"SKIP"→SKIPPED`, `"FAIL"/"ERROR"→FAILED`, иначе `OK`.

---

## 📊 Diagnostics — конвертация DiagnosticItem → ReportDiagnostic

```python
def to_report_diagnostics(errors, warnings) -> list[ReportDiagnostic]
def split_report_diagnostics(errors, warnings) -> tuple[list[ReportDiagnostic], list[ReportDiagnostic]]
```

- Принимают `Iterable[DiagnosticItem | ReportDiagnostic] | None`.
- `DiagnosticItem` → `ReportDiagnostic` с `fallback_severity` ("error" или "warning").
- `ReportDiagnostic` pass-through.
- `split_report_diagnostics()` возвращает `(errors_list, warnings_list)` по `severity`.

---

## 📊 Legacy ReportCollector

`connector/domain/reporting/collector.py` содержит `ReportCollector` — mutable builder, сохранённый для обратной совместимости.

> **Важно**: `ReportCollector` **не является** каноническим owner-ом ingestion pipeline. Canonical путь записи — `IReportSink.emit(event)` → `InMemoryReportContext.append()`. `ReportCollector` может использоваться в изолированных тестах или legacy-адаптерах, но в runtime pipeline его использовать **не следует**.

API collector дублирует event-driven семантику: `set_meta()`, `set_context()`, `add_op()`, `add_item()`, `finish()`, `build()` → `ReportEnvelope`.

---

## 🔄 Context-пространство имён

Подробная таблица — см. [ReportContextKey](#reportcontextkey-str-enum) выше.

Общий принцип: каждый context-блок устанавливается один раз через `SetContextEvent`. Повторный `SetContextEvent` с тем же ключом **перезаписывает** блок целиком (не merge).

Исключение: `ActivityMetricEvent` → merge в `context["stats"][name]`.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Взаимодействие | Направление |
|------|---------------|------------|
| **report-pipeline** (adapters) | `StageResultReporter` пишет в `IReportSink`, читает `ReportPolicy` | → sink, ← policy |
| **report-delivery** (runtime) | Создаёт `InMemoryReportContext` + `ReportSink`, вызывает `ReportAssembler.assemble()` | Creates, Finalizes |
| **usecases** | Получают `IReportSink` + `ReportPolicy`, пишут через адаптеры | → sink |
| **delivery/presenters** | `ApplyReportPresenter` пишет через `IReportSink.emit(...)` | → sink |
| **infra/artifacts** | `JsonReportRenderer` рендерит `ReportEnvelope` | ← envelope |
| **domain/models** | `RowRef`, `DiagnosticItem`, `DiagnosticStage` — shared domain types | ← import |

---

## 🔌 Контракты и границы

1. **Единый ingestion API**: внешние продюсеры пишут **только** через `IReportSink.emit(event)`. Прямой вызов `context.append()` допускается только внутри `ReportSink`.
2. **Immutable события**: все `ReportEvent` — frozen dataclass, не мутируются после создания.
3. **Snapshot isolation**: все snapshot-методы возвращают `deepcopy()`.
4. **Bounded memory**: row-level items ограничены `items_limit`; full event-log по строкам не хранится.
5. **Typed contracts**: context-ключи и op-ключи нормализуются через enums; пустые строки → `ValueError`.
6. **Schema v2**: `schema_version="2.0"`, tri-state status, nullable `RowRef.line_no`.

---

## 💡 Типичные сценарии

### Сценарий 1: Стандартная команда transform (normalize/enrich/mapping)

```python
# 1. Runtime orchestrator создаёт context и sink
context = InMemoryReportContext(run_id=run_id, command="normalize")
sink = ReportSink(context)
assembler = ReportAssembler(context=context)

# 2. Начальная конфигурация
sink.emit(SetMetaEvent(dataset="employees", items_limit=1000))
sink.emit(SetContextEvent(name=ReportContextKey.CONFIG, value={...}))

# 3. UseCase использует StageResultReporter (см. report-pipeline.md)
# reporter.process(result) → sink.emit(AddItemEvent(...))
# reporter.publish_context() → sink.emit(SetContextEvent(...))

# 4. Финализация
sink.emit(FinishEvent(duration_ms=1500))
envelope = assembler.assemble()
# envelope.status = "SUCCESS" | "PARTIAL" | "FAILED"
```

### Сценарий 2: Import-apply с pre-aggregated items

```python
# ApplyReportPresenter публикует уже агрегированные данные:
sink.emit(SetRowCountersEvent(rows_total=100, rows_passed=95, rows_blocked=5, ...))
sink.emit(AddItemEvent(status="FAILED", ..., preaggregated=True))  # не инкрементирует счётчики
sink.emit(SetStatusEvent(status="PARTIAL"))
```

### Сценарий 3: Подсистемная телеметрия

```python
# IActivitySink facade (не требует знания ReportEvent)
activity_sink: IActivitySink = report_sink  # ReportSink реализует оба протокола
activity_sink.emit_activity("dictionary", {"lookups": 150, "hits": 140})
# → context["stats"]["dictionary"] = {"lookups": 150, "hits": 140}
```

### Сценарий 4: Без отчёта (административная команда)

```python
sink = NullReportSink()
# Все emit() вызовы безопасно игнорируются — no-op
```

---

## 📌 Важные детали

### 🚨 Failure Modes

| Ситуация | Поведение | Как обрабатывать |
|----------|----------|------------------|
| Неизвестный тип события | `TypeError` в `append()` | Использовать только typed events из `events.py` |
| Пустой context key | `ValueError` в normalizer | Всегда использовать `ReportContextKey` enum |
| `items_limit` = None | Безлимитное хранение items | Для production всегда задавать через `SetMetaEvent` |
| `preaggregated=True` без `SetRowCountersEvent` | Счётчики не обновятся | Всегда вызывать `SetRowCountersEvent` перед preaggregated items |
| `SetStatusEvent` перед `FinishEvent` | Явный статус перекрывает `_derive_status()` | Корректное поведение для apply-сценариев |
| `FinishEvent` без `SetStatusEvent` | `_derive_status()` вычислит по счётчикам | Стандартный поток для transform-команд |

### ⚠️ Инварианты системы

1. **Append-only**: raw events не мутируются после записи в context.
2. **Deterministic assembly**: одинаковый набор событий → одинаковый envelope.
3. **Single producer API**: внешние продюсеры пишут только через `IReportSink.emit()`.
4. **Streaming row aggregation**: row-level события агрегируются на лету, full raw event-log не хранится.
5. **Bounded sampling**: items ограничены `items_limit`; `items_truncated=True` при превышении.
6. **Status consistency**: `_derive_status()` зависит **только** от `rows_blocked` и `rows_passed`, не от наличия ошибок в diagnostics.

### ⏱️ Performance заметки

- `deepcopy()` при каждом `snapshot()` — O(items + context). Для стандартного запуска с `items_limit=1000` — незначительно.
- `_count_diagnostics()` вызывается на каждый `AddItemEvent` — O(errors + warnings per item).
- `normalize_item_status()` compat bridge — O(1) string comparison.
- Для 100k+ строк: row-level events не хранятся, только counters + bounded sample → memory O(items_limit).

---

## 🛠️ Как расширять

### Добавить новый тип события

1. Создать frozen dataclass в `connector/domain/reporting/events.py`, наследующий `ReportEvent`.
2. Добавить обработку в `InMemoryReportContext.append()`.
3. Если нужно — добавить обработку в `ReportCollector` (legacy).
4. Обновить тесты в `tests/unit/reporting/`.

### Добавить новый context-ключ

1. Добавить значение в `ReportContextKey` enum в `contracts.py`.
2. Использовать в `SetContextEvent(name=ReportContextKey.NEW_KEY, value={...})`.
3. Документировать owner в таблице выше.

### Добавить новый op-ключ

1. Добавить значение в `ReportOpKey` enum в `contracts.py`.
2. Использовать в `AddOpEvent(name=ReportOpKey.NEW_OP, ok=N)`.

### Добавить новый enricher

1. Создать класс, реализующий `IReportEnricher`.
2. Зарегистрировать в `CompositeReportEnricher` при создании `ReportAssembler`.
3. Enricher мутирует envelope in-place (envelope — snapshot, не shared).

### Добавить новый policy capability

1. Добавить поле в `ReportPolicyCapabilities` в `policy.py`.
2. Обновить `REPORT_POLICY_PROFILE_MATRIX` в `policy_matrix.py` для всех профилей.
3. Добавить resolver-метод в `ReportPolicy` если нужен CLI override.
4. Обновить `_validate_matrix_entry()` — автоматически проверит completeness.

---

## 🔗 Связанные документы

- [Report Pipeline — Stage Adapters и Data Flow](./report-pipeline.md)
- [Report Delivery — Runtime Orchestration и Artifact Lifecycle](./report-delivery.md)
- [Report Layer — Реестр Архитектурных Проблем](./report-architecture-issues.md)
- [REPORT-DEC-001: Execution Context + event-driven сборка](../../adr/report/REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-007: Report Schema v2](../../adr/report/REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)
- [REPORT-DEC-008: Report Policy Capability Profiles](../../adr/report/REPORT-DEC-008-report-policy-capability-profiles-and-contract.md)

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Report Models | xORex-LC |
| 2026-03-03 | Документация обновлена после рефакторинга слоя | xORex-LC |