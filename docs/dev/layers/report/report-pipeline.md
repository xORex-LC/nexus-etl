# Report Pipeline — Stage Adapters и Data Flow

> **Adapter model**: `StageResultReporter` — canonical adapter, конвертирующий `TransformResult` в `AddItemEvent` через `IReportSink` с stage-scoped фильтрацией диагностик, policy-based хранением items и маскировкой payload через pluggable strategy.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [📊 StageResultReporter — canonical stage adapter](#-stageresultreporter--canonical-stage-adapter)
  - [Конструктор](#конструктор)
  - [process() — алгоритм обработки одной строки](#process--алгоритм-обработки-одной-строки)
  - [_filter_for_report() — stage-scoped фильтрация](#_filter_for_report--stage-scoped-фильтрация)
  - [publish_context() — публикация stage counters](#publish_context--публикация-stage-counters)
  - [snapshot() — immutable stats](#snapshot--immutable-stats)
- [📊 Strategies — stage-specific поведение](#-strategies--stage-specific-поведение)
  - [IStageReportStrategy (Protocol)](#istagestrategy-protocol)
  - [TransformStageReportStrategy](#transformstagereportstrategy)
  - [PlanningStageReportStrategy](#planningstagereportstrategy)
- [📊 ExecutionStatsAccumulator / StageExecutionStats](#-executionstatsaccumulator--stageexecutionstats)
- [📊 StageCommandResultResolver — stats → CommandResult](#-stagecommandresultresolver--stats--commandresult)
- [📊 PayloadSanitizer — маскировка секретов](#-payloadsanitizer--маскировка-секретов)
- [📊 ApplyReportPresenter — import-apply adapter](#-applyreportpresenter--import-apply-adapter)
- [📊 DiagnosticItem → ReportDiagnostic конвертация](#-diagnosticitem--reportdiagnostic-конвертация)
- [🔄 UseCase Integration Pattern](#-usecase-integration-pattern)
- [🔄 Context-блоки: кто и что пишет](#-context-блоки-кто-и-что-пишет)
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

**Назначение**: Описать stage-level адаптеры, которые конвертируют результаты ETL-стадий в report-события — через canonical `StageResultReporter`, pluggable strategies и `ApplyReportPresenter` для import-apply.

**Ключевая ответственность**:
- Адаптировать `TransformResult` к `AddItemEvent` через `StageResultReporter` с stage-only status policy.
- Фильтровать диагностику по стадии (upstream vs. текущая) для точного атрибутирования ошибок.
- Маскировать секретные поля в payload через `PayloadSanitizer`.
- Предоставить strategy-контракт `IStageReportStrategy` для различий между transform и planning стадиями.
- Накапливать immutable stage-статистику через `ExecutionStatsAccumulator` → `StageExecutionStats`.
- Разрешать системные коды `CommandResult` через `StageCommandResultResolver`.
- Адаптировать `ApplyResult` к набору report-событий через `ApplyReportPresenter`.

**Расположение в кодовой базе**:
- `connector/domain/reporting/adapters/stage_result_reporter.py` — `StageResultReporter`
- `connector/domain/reporting/adapters/strategies.py` — `IStageReportStrategy`, `TransformStageReportStrategy`, `PlanningStageReportStrategy`
- `connector/domain/reporting/adapters/stats_accumulator.py` — `ExecutionStatsAccumulator`, `StageExecutionStats`
- `connector/domain/reporting/adapters/result_policy.py` — `StageCommandResultResolver`
- `connector/domain/reporting/adapters/payload_sanitizer.py` — `PayloadSanitizer`
- `connector/delivery/presenters/apply_report_presenter.py` — `ApplyReportPresenter`
- `connector/domain/reporting/diagnostics.py` — `to_report_diagnostics()`, `split_report_diagnostics()`
- `connector/common/sanitize.py` — `maskSecretsInObject()`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/domain/reporting/adapters/
├── __init__.py                  # Публичный API: реэкспорт всех адаптеров
├── stage_result_reporter.py     # StageResultReporter (canonical adapter)
├── strategies.py                # IStageReportStrategy, TransformStage*, PlanningStage*
├── stats_accumulator.py         # ExecutionStatsAccumulator, StageExecutionStats
├── result_policy.py             # StageCommandResultResolver
└── payload_sanitizer.py         # PayloadSanitizer

connector/delivery/presenters/
└── apply_report_presenter.py    # ApplyReportPresenter (import-apply)

connector/domain/reporting/
└── diagnostics.py               # DiagnosticItem → ReportDiagnostic конвертация
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Report Layer Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml) | Структура adapters, strategies, accumulator |
| Sequence | [Report Layer Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml) | Поток: UseCase → Reporter → Sink → Context |

### 🎭 Применённые паттерны

#### Паттерн 1: Strategy (Stage Differences)

**Где применяется**: `IStageReportStrategy` — абстрагирует stage-specific поведение: skip policy, payload projection, meta projection.

**Реализация в коде**:
- **Protocol**: `IStageReportStrategy` в `strategies.py`
- **Transform**: `TransformStageReportStrategy` — для normalize/mapping/enrich (never skip, standard meta)
- **Planning**: `PlanningStageReportStrategy` — для match/resolve (custom meta_builder, custom should_skip)

**Зачем**: Один canonical `StageResultReporter` для всех стадий. Различия инкапсулированы в strategy, а не в дублировании process()-логики.

#### Паттерн 2: Adapter (TransformResult → ReportEvent)

**Где применяется**: `StageResultReporter` — canonical adapter между pipeline domain и report domain.

**Реализация в коде**: `stage_result_reporter.py`

**Зачем**: Pipeline domain (`TransformResult`) не зависит от report domain. Адаптер выполняет конвертацию, фильтрацию, маскировку и запись.

#### Паттерн 3: Accumulator → Immutable Snapshot

**Где применяется**: `ExecutionStatsAccumulator` (mutable) → `StageExecutionStats` (frozen).

**Реализация в коде**: `stats_accumulator.py`

**Зачем**: Отделить фазу накопления (per-row `on_row()`) от фазы публикации (`snapshot()`). Snapshot immutable — безопасно передавать за пределы адаптера.

#### Паттерн 4: Presenter (ApplyResult → Events)

**Где применяется**: `ApplyReportPresenter` — delivery-boundary presenter.

**Реализация в коде**: `apply_report_presenter.py`

**Зачем**: `ApplyResult` — pre-aggregated модель (summary уже посчитан). Presenter конвертирует в набор report-событий с `preaggregated=True`.

### Диаграмма зависимостей

```
UseCase
  │
  ├─→ StageResultReporter
  │     ├─→ IStageReportStrategy (strategy)
  │     ├─→ ExecutionStatsAccumulator (stats)
  │     ├─→ PayloadSanitizer (masking)
  │     ├─→ split_report_diagnostics() (conversion)
  │     └─→ IReportSink.emit(AddItemEvent / SetContextEvent)
  │
  └─→ StageCommandResultResolver
        └─→ StageExecutionStats → CommandResult
```

```
ApplyReportPresenter
  └─→ IReportSink.emit(SetRowCountersEvent, AddOpEvent, SetContextEvent,
                        AddItemEvent(preaggregated=True), SetStatusEvent, ...)
```

---

## 🔑 Ключевые абстракции

| Абстракция | Файл | Тип | Назначение |
|------------|------|-----|-----------|
| `StageResultReporter` | `stage_result_reporter.py` | Class | Canonical adapter: TransformResult → report events |
| `IStageReportStrategy` | `strategies.py` | Protocol | Skip/payload/meta strategy для stage |
| `TransformStageReportStrategy` | `strategies.py` | Class | Strategy для normalize/mapping/enrich |
| `PlanningStageReportStrategy` | `strategies.py` | Class | Strategy для match/resolve |
| `ExecutionStatsAccumulator` | `stats_accumulator.py` | Class | Mutable stage counters |
| `StageExecutionStats` | `stats_accumulator.py` | Frozen DC | Immutable snapshot counters |
| `StageCommandResultResolver` | `result_policy.py` | Frozen DC | Stats → CommandResult policy |
| `PayloadSanitizer` | `payload_sanitizer.py` | Class | Secret masking для payload |
| `ApplyReportPresenter` | `apply_report_presenter.py` | Class | ApplyResult → report events |

---

## 📊 StageResultReporter — canonical stage adapter

### Конструктор

```python
StageResultReporter(
    *,
    sink: IReportSink,                        # куда писать события
    report_policy: ReportPolicy,              # capability-based policy
    include_items: bool,                      # хранить ли OK-items (resolves через policy)
    context_key: ReportContextKey | str,      # ключ context-блока stage
    ok_label: str,                            # label для OK-counter в context
    failed_label: str,                        # label для FAILED-counter в context
    strategy: IStageReportStrategy,           # stage-specific поведение
    report_stage: DiagnosticStage | None,     # стадия для фильтрации diagnostics
    include_upstream_diagnostics: bool = False, # включать upstream (resolves через policy)
    stats_accumulator: ExecutionStatsAccumulator | None = None,
    payload_sanitizer: PayloadSanitizer | None = None,
)
```

**Resolver-логика в конструкторе**:
- `include_items` → `report_policy.resolve_include_ok_items(include_items)` — capability AND CLI flag.
- `include_upstream_diagnostics` → `report_policy.resolve_include_upstream_diagnostics(...)`.

### process() — алгоритм обработки одной строки

```python
def process(
    result: TransformResult | None,
    *,
    row_ref: RowRef | None = None,
    force_failed: bool = False,
    errors_override: list[DiagnosticItem] | None = None,
    warnings_override: list[DiagnosticItem] | None = None,
) -> None
```

Алгоритм (10 шагов):

1. **Skip check**: `strategy.should_skip(result)` → return если True.
2. **Collect diagnostics**: errors/warnings из `result` или `overrides`.
3. **Stage filter**: `_filter_for_report()` — оставить только diagnostics текущей stage; посчитать upstream counts.
4. **Determine status**: `force_failed or bool(eff_errors)` → `FAILED`, иначе `OK`. **Stage-only policy**: upstream ошибки не влияют на статус.
5. **Update stats**: `stats.on_row(has_errors, has_warnings)`.
6. **Secret fields**: извлечь из `result.meta["secret_fields"]` или `result.secret_candidates`; `stats.on_secret_fields()`.
7. **Should-store decision**: `FAILED AND policy.include_failed_items` OR `include_items` (OK items).
8. **Build payload**: `strategy.build_payload(result)` → `sanitizer.sanitize(payload, secret_fields)`.
9. **Build meta**: `strategy.build_meta(result, upstream_errors_count, upstream_warnings_count, secret_fields)`.
10. **Emit event**: `sink.emit(AddItemEvent(status, row_ref, payload, errors, warnings, meta, store, preaggregated=False))`.

### _filter_for_report() — stage-scoped фильтрация

```python
def _filter_for_report(errors, warnings) -> (stage_errors, stage_warnings, upstream_errors_count, upstream_warnings_count)
```

- Если `include_upstream_diagnostics=True` или `report_stage=None` → пропустить все без фильтрации.
- Иначе: оставить только diagnostics с `item.stage == report_stage`, посчитать upstream counts.

### publish_context() — публикация stage counters

```python
def publish_context() -> StageExecutionStats
```

1. `snapshot = stats.snapshot()` — immutable.
2. `sink.emit(SetContextEvent(name=context_key, value=snapshot.to_context_payload(ok_label, failed_label)))`.
3. Return snapshot.

### snapshot() — immutable stats

```python
def snapshot() -> StageExecutionStats
```

Делегирует в `stats_accumulator.snapshot()`. Immutable frozen dataclass.

---

## 📊 Strategies — stage-specific поведение

### IStageReportStrategy (Protocol)

```python
class IStageReportStrategy(Protocol):
    def should_skip(self, result: TransformResult | None) -> bool: ...
    def build_payload(self, result: TransformResult | None) -> Any: ...
    def build_meta(self, result, *, upstream_errors_count, upstream_warnings_count, secret_fields) -> dict[str, Any]: ...
```

### TransformStageReportStrategy

Для стандартных transform use-cases: `normalize`, `mapping`, `enrich`.

| Метод | Поведение |
|-------|----------|
| `should_skip()` | Всегда `False` — не пропускает строки |
| `build_payload()` | `result.row` или custom `payload_builder(result)` |
| `build_meta()` | `{"match_key": ..., "secret_candidate_fields": [...], "upstream_errors_count": N, "upstream_warnings_count": N}` |

Конструктор: `TransformStageReportStrategy(payload_builder: Callable | None = None)`.

**Актуальное enrich-поведение**:
- для `normalize` и `mapping` payload по-прежнему обычно строится напрямую из `result.row`;
- для `enrich` use-case теперь передаёт custom `payload_builder`, который использует sink/apply payload projection как **preview boundary**;
- это нужно, чтобы report item не показывал служебные enrich-поля из runtime `row`, если они не входят в outbound sink payload.

### PlanningStageReportStrategy

Для planning use-cases: `match`, `resolve`.

| Метод | Поведение |
|-------|----------|
| `should_skip()` | Делегирует в callback `should_skip(result)` если задан, иначе `False` |
| `build_payload()` | `result.row` или custom `payload_builder(result)` |
| `build_meta()` | `meta_builder(result)` + `upstream_errors_count/warnings_count` (setdefault) |

Конструктор:
```python
PlanningStageReportStrategy(
    *,
    meta_builder: Callable[[TransformResult], dict[str, Any] | None],  # обязательный
    should_skip: Callable[[TransformResult], bool] | None = None,
    payload_builder: Callable[[TransformResult], Any] | None = None,
)
```

---

## 📊 ExecutionStatsAccumulator / StageExecutionStats

### StageExecutionStats (frozen dataclass)

```python
@dataclass(frozen=True)
class StageExecutionStats:
    rows_total: int
    ok_rows: int
    failed_rows: int
    warnings_rows: int
    vault_candidates_rows: int
    vault_candidates_fields_total: int
```

`to_context_payload(ok_label, failed_label)` — проецирует в dict для report context:
```python
{"rows_total": N, ok_label: N, failed_label: N, "warnings_rows": N,
 "vault_candidates_rows": N, "vault_candidates_fields_total": N}
```

### ExecutionStatsAccumulator (mutable)

| Метод | Назначение |
|-------|-----------|
| `on_row(has_errors, has_warnings)` | `rows_total++`; `failed_rows++` или `ok_rows++`; `warnings_rows++` if warnings |
| `on_secret_fields(fields)` | `vault_candidates_rows++`; `vault_candidates_fields_total += len(fields)` |
| `snapshot()` | → `StageExecutionStats` (frozen, immutable) |

Контракт: заполняется per-row, публикуется наружу **только** через `snapshot()`.

---

## 📊 StageCommandResultResolver — stats → CommandResult

```python
@dataclass(frozen=True)
class StageCommandResultResolver:
    success_code: SystemErrorCode = SystemErrorCode.OK
    failed_code: SystemErrorCode = SystemErrorCode.DATA_INVALID
    conflict_code: SystemErrorCode = SystemErrorCode.CONFLICT
```

```python
def resolve(stats: StageExecutionStats, *, has_conflicts: bool = False) -> CommandResult
```

| Условие | Действие |
|---------|---------|
| `stats.failed_rows > 0` | `result.add_code(failed_code)` |
| `stats.failed_rows == 0` | `result.add_code(success_code)` |
| `has_conflicts=True` | `result.add_code(conflict_code)` (дополнительно) |

UseCase формирует `CommandResult` через resolver, **не** в runtime.

---

## 📊 PayloadSanitizer — маскировка секретов

```python
class PayloadSanitizer:
    def sanitize(self, payload_obj: Any, *, secret_fields: Iterable[str] | None = None) -> Any
```

Алгоритм:
1. `dict` → `maskSecretsInObject(payload)`.
2. `dataclass` → `asdict()` → `maskSecretsInObject()`.
3. Прочие → `maskSecretsInObject()`.
4. Если `secret_fields` заданы и результат — dict → `sanitized[field] = "***"` для каждого.

Используется `connector/common/sanitize.py :: maskSecretsInObject()`.

---

## 📊 ApplyReportPresenter — import-apply adapter

```python
class ApplyReportPresenter:
    @staticmethod
    def present(result: ApplyResult, sink: IReportSink, plan: Plan,
                apply_context: dict | None, runtime_context: dict | None) -> None
```

**Boundary**: пишет **только** через `IReportSink.emit(...)`, не читает текущее состояние report context.

Алгоритм `present()`:

| Шаг | Событие | Данные |
|-----|---------|--------|
| 1 | `SetRowCountersEvent` | Pre-aggregated: rows_total, rows_passed (created+updated), rows_blocked (failed), rows_skipped, rows_with_warnings |
| 2 | `AddOpEvent` × 4 | CREATE (ok), UPDATE (ok), SKIP (count), APPLY_FAILED (failed) |
| 3 | `SetContextEvent(APPLY)` | apply_context + error_stats + retention_stats + runtime_context |
| 4 | `MergeOpFieldsEvent(PLAN)` | planned_create, planned_update из Plan |
| 5 | `AddItemEvent` × N | Per outcome: `preaggregated=True`, status, row_ref, diagnostics, meta (op, target_id) |
| 6 | `SetItemsTruncatedEvent` | `result.outcomes_truncated` |
| 7 | `EnsureErrorsTotalAtLeastEvent` | `summary.failed` (если failed > 0) |
| 8 | `SetStatusEvent` | SUCCESS / PARTIAL / FAILED по формуле |

**Ключевой момент**: `AddItemEvent(preaggregated=True)` — row counters **не** инкрементируются контекстом, т.к. уже установлены через `SetRowCountersEvent`.

---

## 📊 DiagnosticItem → ReportDiagnostic конвертация

```python
def to_report_diagnostics(errors, warnings) -> list[ReportDiagnostic]
def split_report_diagnostics(errors, warnings) -> (errors_list, warnings_list)
```

- Принимают `Iterable[DiagnosticItem | ReportDiagnostic] | None`.
- `DiagnosticItem` → `ReportDiagnostic` с маппингом полей (severity, stage, code, field, message, rule, details).
- `ReportDiagnostic` → pass-through.
- `split_report_diagnostics()` — то же + split по `severity`.

Используется `StageResultReporter` (шаг 10) и `ApplyReportPresenter` (шаг 5).

---

## 🔄 UseCase Integration Pattern

Все ETL use-cases (normalize, enrich, mapping, match, resolve) следуют единому паттерну:

```python
class SomeUseCase:
    def run(self, ..., report_sink: IReportSink, report_policy: ReportPolicy, ...) -> CommandResult:
        # 1. Создать reporter
        reporter = StageResultReporter(
            sink=report_sink,
            report_policy=report_policy,
            include_items=self.include_items,
            context_key=ReportContextKey.NORMALIZE,  # stage-specific
            ok_label="normalized_ok",
            failed_label="normalize_failed",
            strategy=TransformStageReportStrategy(),  # или PlanningStageReportStrategy
            report_stage=DiagnosticStage.NORMALIZE,
        )

        # 2. Обработать каждый результат
        for result in pipeline.run(source):
            reporter.process(result)

        # 3. Опубликовать stage context
        stats = reporter.publish_context()

        # 4. Разрешить CommandResult
        return StageCommandResultResolver().resolve(stats)
```

**Import-apply** — другой паттерн: `ImportApplyService.apply_plan()` → `ApplyResult` → `ApplyReportPresenter.present(result, sink, plan)`.

### Примеры конфигурации strategy по командам

| Команда | Strategy | context_key | ok_label | failed_label | report_stage |
|---------|----------|-------------|----------|-------------|-------------|
| `normalize` | `TransformStageReportStrategy()` | `NORMALIZE` | `normalized_ok` | `normalize_failed` | `NORMALIZE` |
| `mapping` | `TransformStageReportStrategy()` | `MAPPING` | `mapped_ok` | `map_failed` | `MAP` |
| `enrich` | `TransformStageReportStrategy(payload_builder=...)` | `ENRICH` | `enriched_ok` | `enrich_failed` | `ENRICH` |
| `match` | `PlanningStageReportStrategy(meta_builder=...)` | `MATCH` | `matched_ok` | `match_failed` | `MATCH` |
| `resolve` | `PlanningStageReportStrategy(meta_builder=..., should_skip=...)` | `RESOLVE` | `resolved_ok` | `resolve_failed` | `RESOLVE` |

---

## 🔄 Context-блоки: кто и что пишет

| ReportContextKey | Продюсер | Когда |
|-----------------|----------|------|
| `CONFIG` | Runtime orchestrator | Инициализация |
| `INPUT` | Runtime orchestrator | Инициализация |
| `RUNTIME` | Runtime orchestrator | Финализация |
| `REPORT_POLICY` | Runtime orchestrator | Инициализация |
| `STATS` | IActivitySink (ActivityMetricEvent) | По запросу подсистем |
| `DICTIONARY` | Command handler (`attach_dictionary_report_snapshot`) | После инициализации |
| `TARGET_RUNTIME` | Command handler | После инициализации target |
| `VAULT_ROLLOUT` | Command handler | После vault rollout |
| `APPLY` | ApplyReportPresenter | После apply |
| `APPLY_TARGET` | Command handler | До/после apply |
| `CACHE_STATUS` | Cache commands | После cache status check |
| `CACHE_CLEAR` | Cache commands | После cache clear |
| `CACHE_REFRESH` | Cache commands | После cache refresh |
| `NORMALIZE` | StageResultReporter.publish_context() | После обработки всех строк |
| `MAPPING` | StageResultReporter.publish_context() | После обработки всех строк |
| `ENRICH` | StageResultReporter.publish_context() | После обработки всех строк |
| `MATCH` | StageResultReporter.publish_context() | После обработки всех строк |
| `RESOLVE` | StageResultReporter.publish_context() | После обработки всех строк |

---

## 🔄 Взаимодействие с другими слоями

| Слой | Взаимодействие | Направление |
|------|---------------|------------|
| **report-models** (domain) | Использует `IReportSink`, `ReportPolicy`, events, contracts | ← import |
| **report-delivery** (runtime) | Runtime orchestrator передаёт `IReportSink` + `ReportPolicy` в handler/usecase | ← injection |
| **usecases** | Создают `StageResultReporter`, вызывают `process()` / `publish_context()` | → sink |
| **delivery/presenters** | `ApplyReportPresenter` пишет через `IReportSink` | → sink |
| **transform domain** | `TransformResult` — входной тип для адаптеров | ← import |
| **planning domain** | `Plan`, `ApplyResult` — входные типы для presenter | ← import |
| **diagnostics domain** | `CommandResult`, `SystemErrorCode` — выходные типы resolver | ← import |

---

## 🔌 Контракты и границы

1. **Single canonical adapter**: `StageResultReporter` — единственный путь конвертации `TransformResult → report item`. Нет дублирования process()-логики.
2. **Stage-only status policy**: `item.status` определяется только ошибками текущей стадии, не upstream.
3. **Immutable stats contract**: `StageExecutionStats` — frozen, не мутируется после `snapshot()`.
4. **Unidirectional flow**: Адаптеры пишут в `IReportSink`, не читают из `IReportContext`.
5. **Strategy encapsulation**: Различия стадий инкапсулированы в strategy, не в условной логике reporter-а.
6. **Pre-aggregated bridge**: `ApplyReportPresenter` использует `preaggregated=True` + `SetRowCountersEvent`. Контекст не пересчитывает row-счётчики для этих items.
7. **UseCase owns result**: `CommandResult` формируется в usecase через `StageCommandResultResolver`, не в runtime.

---

## 💡 Типичные сценарии

### Сценарий 1: Normalize stage с полной детализацией

```python
reporter = StageResultReporter(
    sink=report_sink,
    report_policy=ReportPolicy.standard(),
    include_items=True,
    context_key=ReportContextKey.NORMALIZE,
    ok_label="normalized_ok",
    failed_label="normalize_failed",
    strategy=TransformStageReportStrategy(),
    report_stage=DiagnosticStage.NORMALIZE,
)

for result in pipeline.run(source):
    reporter.process(result)  # → AddItemEvent per row

stats = reporter.publish_context()  # → SetContextEvent(NORMALIZE, {...})
command_result = StageCommandResultResolver().resolve(stats)
```

### Сценарий 2: Match stage с custom meta

```python
reporter = StageResultReporter(
    sink=report_sink,
    report_policy=report_policy,
    include_items=include_matched_items,
    context_key=ReportContextKey.MATCH,
    ok_label="matched_ok",
    failed_label="match_failed",
    strategy=PlanningStageReportStrategy(
        meta_builder=lambda r: {"match_status": r.row.match_decision.status.value if r.row else None},
    ),
    report_stage=DiagnosticStage.MATCH,
)

for matched in iter_ok(pipeline.run(source)):
    force_failed = bool((matched.meta or {}).get("match_drop_reason"))
    reporter.process(matched, force_failed=force_failed)

stats = reporter.publish_context()
return StageCommandResultResolver().resolve(stats, has_conflicts=stats.failed_rows > 0)
```

### Сценарий 3: Import-apply

```python
apply_result = apply_service.apply_plan(plan, ...)
ApplyReportPresenter.present(
    result=apply_result,
    sink=report_sink,
    plan=plan,
    apply_context={"dry_run": False},
    runtime_context={"target": "ankey_rest"},
)
```

### Сценарий 4: Resolve с expired pending и special ops

```python
# Expired rows пишутся напрямую через sink (вне StageResultReporter)
for expired_row in pending_expiry.drain_expired():
    sink.emit(AddItemEvent(status=ReportItemStatus.FAILED, row_ref=..., errors=..., store=True))
sink.emit(AddOpEvent(name=ReportOpKey.RESOLVE_EXPIRED, failed=expired_count))

# Основной поток — через reporter
for resolved in resolved_stream:
    reporter.process(resolved)
```

---

## 📌 Важные детали

### 🚨 Failure Modes

| Ситуация | Поведение | Как обрабатывать |
|----------|----------|------------------|
| `result=None` в `process()` | Обрабатывается корректно: empty errors/warnings, status=OK | Допустимо для edge cases |
| `strategy.should_skip()=True` | Строка полностью пропускается, не считается в stats | Для resolve: pending-only rows без resolve-результата |
| `force_failed=True` без errors | Status=FAILED, но diagnostics пустые | Корректно для match_drop_reason |
| `preaggregated=True` без `SetRowCountersEvent` | Counters останутся 0 | Всегда вызывать SetRowCountersEvent перед preaggregated items |
| `report_stage=None` | Фильтрация diagnostics отключена — все проходят | Для стадий без stage-scoped диагностик |

### ⚠️ Инварианты системы

1. **Single processing algorithm**: row-processing логика существует только в `StageResultReporter.process()`.
2. **Stage-only status policy**: item status зависит только от stage-local ошибок; upstream diagnostics → только metadata (`upstream_errors_count`).
3. **Immutable stats**: `StageExecutionStats` не мутируется после фиксации.
4. **No business logic in strategy**: strategy решает only skip/payload/meta, не status и не counters.
5. **Deterministic context publishing**: `publish_context()` вызывается один раз после обработки всех строк.
6. **Presenter write-only**: `ApplyReportPresenter` пишет через `IReportSink.emit()`, не читает context.

### ⏱️ Performance заметки

- `process()` — O(errors + warnings) на строку для фильтрации и конвертации.
- `PayloadSanitizer.sanitize()` — O(fields) для dict, O(fields) для dataclass через `asdict()`.
- `StageExecutionStats.to_context_payload()` — O(1).
- Для 100k+ строк: `AddItemEvent` emit-ится на каждую строку, но контекст хранит только bounded sample.

---

## 🛠️ Как расширять

### Добавить новую стадию

1. Выбрать strategy: `TransformStageReportStrategy` или `PlanningStageReportStrategy`.
2. В usecase: создать `StageResultReporter` с новым `context_key` и `report_stage`.
3. Добавить `context_key` в `ReportContextKey` enum (если ещё нет).
4. Вызвать `reporter.publish_context()` после обработки.

### Добавить custom strategy

1. Создать класс, реализующий `IStageReportStrategy`.
2. Определить `should_skip()`, `build_payload()`, `build_meta()`.
3. Передать в `StageResultReporter(strategy=MyStrategy())`.

### Добавить новый op-ключ

1. Добавить значение в `ReportOpKey` enum.
2. Emit через `sink.emit(AddOpEvent(name=ReportOpKey.NEW_OP, ok=N))`.

### Добавить данные в ApplyReportPresenter

1. Новые поля → в `SetContextEvent(APPLY, value={...})`.
2. Новые op-счётчики → в `AddOpEvent`.
3. Новые item-метаданные → в `AddItemEvent.meta`.

---

## 🔗 Связанные документы

- [Report Models — Event-Driven Domain и Policy Framework](./report-models.md)
- [Report Delivery — Runtime Orchestration и Artifact Lifecycle](./report-delivery.md)
- [Report Layer — Реестр Архитектурных Проблем](./report-architecture-issues.md)
- [REPORT-DEC-002: Unified StageResultReporter](../../adr/report/REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-003: ReportWritePort и инкапсуляция](../../adr/report/REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Report Pipeline | xORex-LC |
| 2026-03-03 | Документация обновлена после рефакторинга слоя | xORex-LC |
| 2026-05-06 | Уточнена enrich-specific payload projection: `TransformStageReportStrategy` для enrich теперь обычно получает sink-aware `payload_builder`, чтобы report payload показывал preview outbound payload, а не сырой runtime `row` | xORex-LC |
