# Observability Runtime (Wiring, Lifecycle & CLI)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Lifecycle команды](#lifecycle-команды)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 DI-провайдеры (ObservabilityContainer)](#-di-провайдеры-observabilitycontainer)
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

**Назначение**: Связать observability с жизненным циклом CLI-команды — инициализировать structlog
runtime через DI, привязать корреляционный контекст, запустить startup-ретенцию, на финализации
записать артефакты/ledger/указатели, и предоставить CLI-команды для эксплуатации.

**Ключевая ответственность**: Оркестрация observability на границе `delivery/cli` (init → handler →
finalize → shutdown) + DI-wiring + CLI (`maintenance prune`, `obs latest|tail`).

**Расположение в кодовой базе**:
- `connector/delivery/cli/runtime/orchestrator.py` — observability-части lifecycle
- `connector/delivery/cli/containers.py` — `ObservabilityContainer`
- `connector/delivery/cli/component_mapping.py` — `command → ServiceComponent`
- `connector/delivery/commands/maintenance_prune.py`, `obs_artifacts.py` — CLI-handlers
- `connector/delivery/presenters/observability_presenter.py` — вывод

> Общий lifecycle `run_with_report`/`run_without_report` (report-аспект) описан в
> [report-delivery.md](../report/report-delivery.md). Здесь — **observability-специфика**.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
delivery/cli/
├── runtime/orchestrator.py
│   ├── RuntimeObservabilitySession            # component + layout + runtime + logger на один run
│   ├── _initialize_observability_session()    # override component/stderr_stream → init logging_runtime
│   ├── _run_observability_sweeper()           # best-effort startup retention (logs/reports/plans/ledger)
│   ├── _record_run_ledger_for_report()/_without_report()  # best-effort ledger append
│   ├── _publish_latest_artifact_pointers*()   # best-effort current.log/latest.json
│   └── finalize_report_artifacts()            # render отчёта по layout
├── containers.py → ObservabilityContainer     # DI-провайдеры (Resource/Singleton/Object)
└── component_mapping.py → component_for_command()

delivery/commands/
├── maintenance_prune.py   # nexus maintenance prune
└── obs_artifacts.py       # nexus obs latest|tail

delivery/presenters/observability_presenter.py  # render_prune / render_latest / render_tail
```

### 🎭 Применённые паттерны

#### Паттерн 1: Session object (per-run aggregate)

**Где применяется**: `RuntimeObservabilitySession` связывает `component` + `layout` + активный
`StructuredLoggingRuntime` + `logger` + `log_file_path` на один lifecycle команды.

**Зачем**: один типизированный объект прокидывается по шагам финализации; teardown остаётся за DI
Resource (сессия им не владеет).

#### Паттерн 2: Best-effort sidecar

**Где применяется**: sweeper / ledger / pointers — каждый шаг обёрнут в try/except с WARNING; никогда
не меняет exit code команды.

#### Паттерн 3: DI lifecycle tiers

**Где применяется**: `ObservabilityContainer` — `Resource` только для объектов с teardown
(`logging_runtime`), `Singleton`/`Object` для stateless. См. [таблицу провайдеров](#-di-провайдеры-observabilitycontainer).

### Lifecycle команды

```
run_with_report / run_without_report:
  1. create_container(); override app_config
  2. _initialize_observability_session():
       container.observability.component.override(component_for_command(cmd))
       container.observability.stderr_stream.override(original_stderr)
       container.observability.logging_runtime.init()      # configure structlog (Resource)
       logger = runtime.get_logger(component)            # structlog BoundLogger
  3. bind_observability_context(run_id, pipeline_run_id, component, dataset)
  4. _run_observability_sweeper()                          # best-effort startup retention
  5. sys.stdout/stderr = TeeStream(original, StdStreamToLogger(redaction))
  6. validate → init resources → topology bootstrap → handler(...)
  ── finally ──────────────────────────────────────────────────────────────
  7. sys.stdout/stderr = original_*          ◀── ВОССТАНОВИТЬ ДО shutdown (анти-recursion)
  8. shutdown_container_resources()          # tears down Resource (logging_runtime.close)
  9. finalize_report_artifacts()             # render отчёта по layout (report-path)
 10. _publish_latest_artifact_pointers*()    # current.log / latest.json (best-effort)
 11. _record_run_ledger_*()                  # ledger append (best-effort)
 12. clear_observability_context()
 13. raise typer.Exit(exit_code_from_result(...))
```

---

## 🔑 Ключевые абстракции

### Основные классы / функции

| Класс/функция | Роль | Ключевое |
|---------------|------|----------|
| `RuntimeObservabilitySession` | Агрегат observability на один run | `component`, `layout`, `runtime`, `logger`, `log_file_path` |
| `_initialize_observability_session()` | Инициализация runtime через DI | override `component`/`stderr_stream` → `logging_runtime.init()` |
| `_run_observability_sweeper()` | Startup-ретенция (best-effort) | `sweep_logs/reports/plans/ledger` |
| `_record_run_ledger_for_report()` / `_without_report()` | Запись ledger (best-effort) | статус из exit-path, counters из envelope |
| `_publish_latest_artifact_pointers*()` | Указатели (best-effort) | log/report/plan |
| `finalize_report_artifacts()` | Рендер отчёта | `render_with_layout(now=meta.finished_at)` |
| `component_for_command()` | `command → ServiceComponent` | fail-fast на неизвестной команде |
| `maintenance_prune.handler` / `obs_artifacts.{latest,tail}_handler` | CLI-handlers | sweeper / viewer |
| `ObservabilityPresenter` | Вывод | `render_prune/latest/tail` |

---

## 🗂️ Модели данных

### Dataclass: `RuntimeObservabilitySession`

```python
@dataclass(frozen=True)
class RuntimeObservabilitySession:
    component: ServiceComponent
    layout: ObservabilityLayout
    runtime: StructuredLoggingRuntime
    logger: Any
    log_file_path: str | None
```

**Lifecycle**: создаётся в `_initialize_observability_session`; используется в финализации
(report-path, pointers, ledger); **не владеет** teardown logging_runtime (это DI Resource).

### CLI option-модели

- `maintenance_prune.Options(component: ServiceComponent | None)` — компонент или все.
- `obs_artifacts.LatestOptions(component, artifact=REPORT)`, `TailOptions(component, artifact=LOG, lines=20)`.
- Presenter DTO: `PruneComponentSummary`, `ArtifactDisplay` (см. `observability_presenter.py`).

---

## 📊 DI-провайдеры (ObservabilityContainer)

| Провайдер | Тип | Почему |
|-----------|-----|--------|
| `logging_runtime` | **Resource** | владеет handler stack + structlog config; нужен teardown (`runtime.close()`) |
| `observability_layout` | Singleton | чистый резолвер, без lifecycle |
| `redaction_policy` / `redaction_engine` | Singleton | value-policy + stateless engine |
| `sweeper` | Factory | stateless; новый на вызов |
| `ledger_backend` | **Singleton** | open-per-append (не держит дескриптор) → не Resource |
| `artifact_viewer` | Singleton | read-side, stateless (поверх ledger_backend) |
| `pointer_publisher` | Singleton | stateless |
| `component_mapper` | Object | чистая функция |
| `component` / `stderr_stream` | Dependency | override per-run в оркестраторе |

**Принцип**: `Resource` — только для объектов с реальным teardown; stateless — `Singleton`/`Factory`;
чистые функции/value — `Object`/`Dependency`. Иначе скатывание в service-locator.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| common/observability | Зависимость | `ServiceComponent`, `ObservabilityArtifactKind`, `ObservabilityLayout` | резолв компонента/путей |
| infra/logging | Использует | `build_structured_logging_runtime`, `bind/clear_observability_context` | runtime логирования |
| infra/artifacts, infra/observability | Использует | renderer/writer/ledger/sweeper/viewer/pointers | финализация и CLI |
| report layer | Использует | `ReportAssembler`, `ReportEnvelope` | контент отчёта + counters для ledger |
| delivery/commands | Регистрирует | `app.py` (Typer) | `maintenance prune`, `obs latest|tail` |

---

## 🔌 Контракты и границы

### Порядок финализации (контракт)

`finally`: **restore streams → shutdown → finalize report → pointers → ledger → clear context**.

- **report → pointers → ledger** именно в этом порядке: ledger/указатели ссылаются на уже записанный
  отчёт; путь отчёта выводится тем же `_resolve_report_artifact_timestamp(envelope)` (= `meta.finished_at`),
  что и фактическая запись.
- **restore streams до shutdown** — обязательно (см. инвариант ниже).

### Статус ledger

`_resolve_ledger_status`: при наличии `final_result` → `SUCCESS` если `exit_code==0`, иначе `FAILED`;
fallback — `envelope.status` (для report-path) / `"SUCCESS"` (для no-report).

### Передача `plan_path`

`import_plan` кладёт путь плана в `ctx.extra["plan_path"]`; оркестратор читает его
`_resolve_runtime_plan_path(ctx, opts)` (или из `opts.plan_path` у `import apply`) — без знания
деталей handler'а.

### Границы слоёв

**Разрешённые**: `delivery/cli` → всё (composition root). `commands` → infra-adapters через
`ctx.container.observability.*` + presenters.
**Запрещённые**: бизнес-логика в commands; прямое конструирование infra-объектов вне DI.

---

## 💡 Типичные сценарии

### Сценарий 1: `nexus obs latest --component enricher`

```
obs_artifacts.latest_handler:
  viewer = ctx.container.observability.artifact_viewer()
  path = viewer.resolve_latest_artifact_path(component=ENRICHER, artifact_kind=REPORT)
  content = viewer.read_text(path)
  echo ObservabilityPresenter.render_latest(ArtifactDisplay(...))   # stdout
```

### Сценарий 2: `nexus maintenance prune [--component X]`

```
maintenance_prune.handler:
  sweeper = ctx.container.observability.sweeper()
  for component in (X or all): sweep_logs/reports/plans/ledger(...)
  echo ObservabilityPresenter.render_prune(summaries)   # stdout
```

---

## 📌 Важные детали

### Особенности реализации

- **Команды obs/maintenance → `ServiceComponent.OBSERVABILITY`** (их собственные логи идут в
  `var/logs/observability/`), при этом они *читают/чистят* артефакты запрошенного компонента.
- **Ledger/pointers warning'и после shutdown** попадают на stderr (через `lastResort` после restore),
  но не в лог-файл (file handler уже закрыт) — известный компромисс порядка finalize-после-shutdown.

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| Сбой sweeper/ledger/pointers | ФС/backend | best-effort: WARNING (`observability`), exit code не меняется | проверить каталог/диск |
| `finalize_report_artifacts` raise | нет `meta.finished_at` / IO | INTERNAL_ERROR как finalize-result | `FinishEvent` эмитится до assemble — в норме не возникает |
| `KeyError` в `component_for_command` | неизвестная команда | fail-fast | расширить `_DIRECT_COMMAND_COMPONENTS` |
| Teardown-recursion (исторический) | root без handlers + `sys.stderr=TeeStream` → `lastResort` петля | **устранено** restore-streams-до-shutdown | — |

### ⚠️ Инварианты системы

1. **Инвариант: restore stdout/stderr ДО shutdown**
   - **Что**: в `finally` первым делом `sys.stdout/stderr = original_*`, затем `shutdown_resources()`.
   - **Почему важно**: `shutdown` закрывает `logging_runtime` (root без handlers); последующий WARNING+
     иначе уходит в `logging.lastResort` → живой `sys.stderr` (TeeStream) → `StdStreamToLogger` → logger
     → root → lastResort → **бесконечная рекурсия, 100% CPU**. Restore разрывает петлю.
   - **Где проверяется**: `test_run_with_report_restores_streams_when_shutdown_fails`.
2. **Инвариант: best-effort observability**
   - **Что**: sweeper/ledger/pointers не влияют на exit code.
   - **Почему важно**: наблюдательный слой не должен ронять основную команду.
   - **Где проверяется**: try/except-обёртки; `test_run_with_report_keeps_success_when_ledger_append_fails`.
3. **Инвариант: read=write пути артефактов**
   - **Что**: ledger/pointers выводят пути тем же layout+timestamp, что и запись.
   - **Почему важно**: ledger ссылается на реально созданные файлы.
   - **Где проверяется**: e2e `test_observability_ledger` / `test_observability_cli`.

### ⏱️ Performance заметки

- Startup-sweeper throttl-ится daily-marker'ами (на компонент/тип) — не добавляет существенной
  латентности на старт; VACUUM SQLite-ledger ≤1/день.

### Частые ошибки

- ❌ Закрывать `logging_runtime` до восстановления потоков.
- ❌ Делать ledger/pointers критичными (влияющими на exit code).
- ✅ Все наблюдательные шаги — best-effort, после restore streams.

---

## 🛠️ Как расширять

### Добавить новую observability CLI-команду

1. Handler в `connector/delivery/commands/<name>.py` (тонкий: `ctx.container.observability.*` + presenter).
2. Зарегистрировать команду в `connector/delivery/cli/app.py`.
3. Добавить маппинг в `component_for_command` (`_DIRECT_COMMAND_COMPONENTS`) → обычно `OBSERVABILITY`.
4. Формат вывода — в `ObservabilityPresenter`.

### Подключить новый артефакт к финализации

1. Добавить путь в `ObservabilityLayout` ([model](./observability-model.md)).
2. Реализовать запись в `infra/artifacts`/`infra/observability` (atomic, layout-aware).
3. Вызвать best-effort на финализации в оркестраторе (после restore streams).

---

## 🔗 Связанные документы

- [Observability Model](./observability-model.md) · [Config](./observability-config.md) ·
  [Logging](./observability-logging.md) · [Artifacts](./observability-artifacts.md)
- [Report Delivery](../report/report-delivery.md) — общий `run_with_report` lifecycle
- [DI Container](../../../adr/delivery/DELIVERY-DEC-006-app-container-composition-root-integration.md) — composition root
- ADR: `OBSERVABILITY-DEC-002` (per-component модель, switch-over)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002 Stages 4–6) | xorex-LC |
