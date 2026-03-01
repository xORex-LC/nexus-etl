# REPORT-DEC-001: Execution Context + event-driven сборка отчёта в Report Layer

> **Статус**: Принято
> **Дата принятия**: 2026-03-01
> **Решает проблему**: REPORT-PROBLEM-001
> **Участники решения**: @xORex-LC
> **Состояние реализации**: Завершено (2026-03-02), compatibility windows закрыты

---

## 📋 Контекст

Report layer накопил смешение ролей между runtime orchestration, сбором telemetry и форматированием финального артефакта.  
Нужна архитектура, где:

- события выполнения собираются единообразно в рамках command scope;
- итоговый отчёт собирается из сырых событий как отдельная стадия;
- rendering не смешивается с ingestion и domain-агрегацией.

---

## 🎯 Решение

Принять модель **Execution Context (Context Object)** для report-слоя:

1. `Report Model (DTO)` — чистые структуры данных (без бизнес-логики и без IO).
2. `IReportSink.emit(event)` — единственный public API для продюсеров runtime/usecase/adapter.
3. `IReportContext` (`InMemoryReportContext`) — internal storage сырых событий; `append(event)` не является producer API.
4. `IActivitySink` — facade/alias над `IReportSink` для подсистем, не зависящих от report-domain типов.
5. `ReportAssembler` + `IReportEnricher` (Strategy + Composite) — строит итоговый `ReportEnvelope` из raw context по `ReportPolicy`.
6. `IReportRenderer` — форматный рендер (`JsonReportRenderer` сейчас, HTML/PDF позже).

Дополнительно:
- разделить **Raw Events** и **Derived Report**;
- зафиксировать правило подключения подсистем: бизнес-контекстные события публикуются явным `sink.emit(...)` из usecase, инфраструктурные метрики допускаются через decorator/facade;
- использовать command scope DI вместо отдельного sub-container.
- lifecycle финализации остаётся в `run_with_report()`; middleware/decorator-вариант остаётся отдельным этапом runtime-декомпозиции.
- migration-window `ReportWritePort` (из `REPORT-DEC-003`) закрыт в post-window cleanup; конечный ingestion boundary для продюсеров — `IReportSink.emit(event)`.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/context.py`
  - `IReportContext`
  - `InMemoryReportContext`
- `connector/domain/reporting/events.py`
  - `ReportEvent` и типизированные события (`CommandLifecycleEvent`, `RowProcessedEvent`, `RuntimeErrorEvent`, `SubsystemMetricEvent`)
  - `RowProcessedEvent` публикуется на каждую обработанную строку, но не хранится как неограниченный raw-log в памяти
- `connector/domain/reporting/sink.py`
  - `IReportSink`, `IActivitySink`, `NullActivitySink`
- `connector/domain/reporting/assembler.py`
  - `ReportAssembler`
  - `ReportPolicy`
  - `CompositeReportEnricher`
- `connector/infra/artifacts/report_renderer.py`
  - `IReportRenderer`
  - `JsonReportRenderer`

**Изменения в существующих компонентах**:
- `connector/delivery/cli/runtime.py` — orchestration + вызов sink/assembler/renderer, без форматной логики отчёта.
- `connector/delivery/presenters/*` — переведены с прямых мутаций collector на публикацию событий в sink.
- `connector/domain/reporting/collector.py` — сохранён как внутренний компонент event-driven сборки, без legacy write-веток.

### Интерфейсы

```python
class IReportSink(Protocol):
    def emit(self, event: ReportEvent) -> None: ...


class IActivitySink(Protocol):
    def emit(self, event: ReportEvent) -> None: ...


class IReportContext(Protocol):
    def append(self, event: ReportEvent) -> None: ...
    def events(self) -> tuple[ReportEvent, ...]: ...


class IReportEnricher(Protocol):
    def enrich(self, context: IReportContext, envelope: ReportEnvelope) -> ReportEnvelope: ...


class IReportRenderer(Protocol):
    def render(self, envelope: ReportEnvelope) -> dict[str, Any]: ...
```

```python
class ReportSink(IReportSink):
    def __init__(self, context: IReportContext) -> None: ...

    def emit(self, event: ReportEvent) -> None:
        # Единственная точка записи raw events.
        self._context.append(event)
```

### Правило подключения подсистем

1. Если для корректной интерпретации события нужен бизнес-контекст сценария, событие публикуется в usecase явным вызовом `sink.emit(...)`.
2. Если нужен только инфраструктурный контекст (duration/error/retry/latency), допускается decorator/facade на `IActivitySink`.
3. На текущем этапе `IActivitySink` не вводит отдельную модель событий; это facade над `IReportSink`.
4. Если в будущем подсистемы начнут публиковать собственные typed-события, вводится отдельный mapper `ActivityEvent -> ReportEvent` как новое ADR-решение.

### Гранулярность событий и memory-strategy

1. `RowProcessedEvent` — одно событие на строку (streaming ingestion).
2. Для row-level событий действует правило production-safety:
   - агрегаты (`rows_total`, stage counters, diagnostics totals) считаются на лету;
   - row-level выборка хранится bounded (по policy/items limit);
   - full raw event-log по строкам в памяти не накапливается.
3. `IReportContext.events()` не является контрактом «вернуть все row-events за запуск»; он предоставляет только bounded/raw-срез, достаточный для assembler/enricher.
4. Полный объём диагностируемых строк отражается через summary/counters, а не через размер raw event-list.

### Поток данных

```
Runtime/UseCase/Adapters
        ↓ (emit ReportEvent)
      IReportSink
        ↓
  Scoped IReportContext (raw events)
        ↓
  ReportAssembler + Composite Enrichers + ReportPolicy
        ↓
    ReportEnvelope (derived)
        ↓
      IReportRenderer (JSON/...)
        ↓
    write artifact
```

### Lifecycle интеграция

- Сборка/финализация отчёта выполняется внутри текущего `run_with_report()` (`try/finally`).
- Введение middleware/decorator-паттерна для финализации не является частью данного решения и относится к runtime-декомпозиции (`REPORT-DEC-005`).

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Чёткое разделение ответственности: ingestion, aggregation, rendering.
- ✅ Единый public API пополнения отчёта: `IReportSink.emit(...)`.
- ✅ Масштабирование детализации отчёта через `ReportPolicy` и `IReportEnricher`, без разрастания runtime.
- ✅ Возможность безопасно добавлять новые форматы рендера без изменения use-case кода.
- ✅ Улучшение тестируемости: assembler/enricher/sink можно тестировать изолированно.

**Недостатки (компромиссы)**:
- ⚠️ Появляется дополнительный архитектурный слой (events/context/assembler).
- ⚠️ Переход от collector-centric write-path к event-driven ingestion потребовал этапной миграции компонентов.
- ⚠️ Нужна дисциплина схемы событий (versioning, typed payload).

**Альтернативы, которые отклонили**:
- ❌ **Продолжать расширять текущий collector**: не устраняет root-cause смешения ролей.
- ❌ **Только прозрачный tracing без явных business events**: ухудшает контроль над семантикой событий сценария.
- ❌ **Отдельный sub-container report layer**: избыточно для текущего масштаба; command scope достаточно.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/reporting/events.py` | Новый event-контракт |
| `connector/domain/reporting/context.py` | Scoped context object |
| `connector/domain/reporting/assembler.py` | Сборка derived report |
| `connector/domain/reporting/sink.py` | Sink/ActivitySink API |
| `connector/infra/artifacts/report_renderer.py` | JSON renderer abstraction |
| `connector/delivery/cli/runtime.py` | Использует sink + assembler + renderer |

### Ключевые методы

- `IReportSink.emit(event)` — единая точка ingestion
- `IReportContext.append(event)` — internal append внутри sink-реализации
- `ReportAssembler.build(context, policy)` — сборка `ReportEnvelope`
- `IReportRenderer.render(envelope)` — форматная проекция в артефакт

### Инварианты

1. **Append-only события**: raw events не мутируются после записи в context.
2. **Deterministic assembly**: одинаковый набор событий + policy -> одинаковый envelope.
3. **Single producer API**: внешние продюсеры пишут только через `IReportSink.emit(...)`.
4. **Streaming row aggregation**: row-level события агрегируются на лету; не допускается unbounded накопление raw row-events в памяти.
5. **Bounded sampling**: context хранит только ограниченную выборку row-level событий/items согласно policy/limit.
6. **Policy-driven detail**: уровень детализации определяется `ReportPolicy`, а не ad-hoc условиями runtime.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: assembler корректно выводит `status/summary` из event-потока.
- ✅ Unit: `IReportSink` является единственной producer entry-point; `IReportContext.append()` не используется напрямую вне sink.
- ✅ Unit: гибридное правило подключения подсистем не приводит к дублированию событий.
- ✅ Unit: policy presets (`minimal/standard/debug`) и capability-contract покрыты отдельно в `REPORT-DEC-008`.
- ✅ Unit: `RowProcessedEvent` при больших потоках не приводит к unbounded memory росту (100k+ строк).
- ✅ Unit: bounded sample items соблюдает `items_limit`/policy и не влияет на итоговые aggregate counters.
- ✅ Unit: secondary runtime errors материализуются как warning events.
- ✅ Integration: команды `mapping/enrich/import-apply/cache-refresh` формируют консистентную event-chain.

**Проверка в runtime**:
1. Включить policy `standard` для всех CLI команд.
2. Сравнить текущий JSON report и новый renderer output на staging.
3. Убедиться, что runtime/subsystem ошибки представлены единообразно.

**Метрики успеха**:
- Доля report-изменений, требующих правок в `runtime.py`, должна снижаться.
- Новая telemetry подсистемы подключается через `IActivitySink` без правок в `ReportAssembler`.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml)
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

**Примеры использования**:

```python
# command scope
context = InMemoryReportContext()
sink = ReportSink(context)

sink.emit(CommandLifecycleEvent.started(command="enrich", run_id=run_id))
sink.emit(RuntimeErrorEvent(stage="ENRICH", code="INTERNAL_ERROR", message="..."))

envelope = ReportAssembler(policy=ReportPolicy.standard()).build(context)
payload = JsonReportRenderer().render(envelope)
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Структура событий требует версионирования (`schema_version`) при эволюции.
- Middleware/decorator финализация пока не вводилась, чтобы не смешивать с runtime-декомпозицией.

**Риски**:
- ⚠️ Рост memory footprint при больших запусках  
  → **Митигация**: streaming aggregation + bounded sample policy (без хранения полного row event-log).

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/cli/runtime.py` | Высокое | Упростить до orchestration + вызвать sink/assembler/renderer |
| `delivery/presenters/apply_report_presenter.py` | Высокое | Перейти с прямой мутации collector на event emission |
| `usecases/*` | Среднее | Публиковать бизнес-контекстные события через явный `sink.emit(...)` |
| `infra decorators/*` | Среднее | Публиковать инфраструктурные метрики через `IActivitySink` facade |
| `infra/artifacts/report_writer.py` | Среднее | Делегировать rendering в `IReportRenderer` |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [Report issues registry](../../dev/layers/report/report-architecture-issues.md)
- ✅ `docs/dev/layers/report/*` синхронизированы с event-driven моделью и schema v2.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)
- [REPORT-DEC-006](./REPORT-DEC-006-report-meta-ownership-policy-and-dataset-boundary.md)
- [REPORT-DEC-007](./REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)
- [REPORT-DEC-008](./REPORT-DEC-008-report-policy-capability-profiles-and-contract.md)
- [Report models](../../dev/layers/report/report-models.md)
- [Report pipeline](../../dev/layers/report/report-pipeline.md)
- [Report delivery](../../dev/layers/report/report-delivery.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-01 | Решение предложено |
| 2026-03-01 | Решение принято после review |
| 2026-03-02 | Уточнены границы `IReportSink/IActivitySink/IReportContext`, гибридное правило подключения подсистем и lifecycle-фаза через `run_with_report()` |
| 2026-03-02 | Зафиксирована production memory-strategy: streaming-агрегация row-events + bounded sample вместо полного raw row-log в памяти |
| 2026-03-02 | Зафиксировано, что `ReportWritePort` — переходный bridge; целевой ingestion API для продюсеров — `IReportSink.emit(event)` |
| 2026-03-02 | Завершен event-driven cutover: bridge-совместимость удалена, canonical producer API — только `IReportSink.emit(event)` |
