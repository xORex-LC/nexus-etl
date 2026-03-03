# Report Delivery — Runtime Orchestration и Artifact Lifecycle

> **Run lifecycle**: `run_with_report()` создаёт `InMemoryReportContext` и `ReportSink` per-command, делегирует handler execution, применяет runtime result mapping, финализирует через `ReportAssembler` и рендерит JSON-артефакт через `IReportRenderer`.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [📑 Дерево модулей](#-дерево-модулей)
- [🏗️ Архитектурные паттерны](#-архитектурные-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [📐 run\_with\_report() — lifecycle с отчётом](#-run_with_report--lifecycle-с-отчётом)
- [📐 run\_without\_report() — lifecycle без отчёта](#-run_without_report--lifecycle-без-отчёта)
- [🎭 runtime\_result\_mapper — маппинг результата в report](#-runtime_result_mapper--маппинг-результата-в-report)
- [🗂️ finalize\_report\_artifacts() — финализация отчёта](#-finalize_report_artifacts--финализация-отчёта)
- [📊 IReportRenderer / JsonReportRenderer](#-ireportrenderer--jsonreportrenderer)
- [🚨 Exception Handling Matrix](#-exception-handling-matrix)
- [🔌 Handler Contract](#-handler-contract)
- [🏗️ DI Wiring — report NOT in containers](#-di-wiring--report-not-in-containers)
- [📊 Exit Code Contract](#-exit-code-contract)
- [📐 JSON Output Format](#-json-output-format)
- [🔄 Interactions](#-interactions)
- [📌 Contracts](#-contracts)
- [💡 Scenarios](#-scenarios)
- [⚠️ Failure Modes](#-failure-modes)
- [🔑 Invariants](#-invariants)
- [⏱️ Performance Notes](#-performance-notes)
- [🛠️ Extension Guide](#-extension-guide)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

Report delivery — слой runtime-оркестрации, который управляет полным lifecycle CLI-команды:
создание report context и sink, инициализация DI container, выполнение handler,
маппинг результата в report-события, финализация envelope и рендеринг JSON-артефакта.

Ключевое разделение ответственности:

| Модуль | Роль |
|--------|------|
| `runtime_orchestrator.py` | Lifecycle orchestration: init → handler → shutdown → finalize |
| `runtime.py` | Thin facade: инжектит production зависимости и делегирует в orchestrator |
| `runtime_result_mapper.py` | Маппинг `DomainCommandResult` → report events (`AddItemEvent`) |
| `result_adapter.py` | Конвертация `DomainCommandResult` ↔ OS exit code |
| `runtime_contracts.py` | Handler protocol, `RuntimeExecutionResult`, `RuntimeErrorWithCode` |
| `report_renderer.py` | Сериализация `ReportEnvelope` → JSON файл |

---

## 📑 Дерево модулей

```
connector/delivery/cli/
├── runtime_orchestrator.py      # Lifecycle orchestration (canonical)
├── runtime.py                   # Thin facade с production DI
├── runtime_contracts.py         # CommandHandler protocol, RuntimeExecutionResult
├── runtime_result_mapper.py     # DomainCommandResult → report events
├── result_adapter.py            # result_with(), exit_code_from_result()
├── context.py                   # UnboundCommandContext, BoundCommandContext
├── requirements.py              # Requirements flags
└── containers.py                # AppContainer DI

connector/infra/artifacts/
└── report_renderer.py           # IReportRenderer, JsonReportRenderer
```

---

## 🏗️ Архитектурные паттерны

### Template Method (orchestration flow)

| Аспект | Описание |
|--------|----------|
| **Где** | `runtime_orchestrator.run_with_report()` |
| **Реализация** | Фиксированный каркас lifecycle (init → handler → shutdown → finalize) с inject-ными callbacks для каждого шага |
| **Пример** | `create_container`, `initialize_container_resources`, `apply_result_to_report`, `finalize_report_artifacts` — все callback-and |
| **Зачем** | Отделяет orchestration skeleton от production wiring; позволяет тестировать lifecycle без реальных DI containers |

### Facade (runtime.py)

| Аспект | Описание |
|--------|----------|
| **Где** | `runtime.run_with_report()`, `runtime.run_without_report()` |
| **Реализация** | Thin facade инжектит `AppContainer`, `_init_container_for_requirements` и другие production зависимости |
| **Пример** | `runtime.run_with_report(ctx=ctx, command_name="enrich", opts=opts, handler=handler, requirements=reqs)` |
| **Зачем** | CLI команды вызывают простой 5-arg API; orchestrator получает полный parameterized interface |

### Write-Once Artifact

| Аспект | Описание |
|--------|----------|
| **Где** | `finalize_report_artifacts()` → `JsonReportRenderer.render()` |
| **Реализация** | Envelope собирается один раз через `ReportAssembler.assemble()` и записывается как immutable JSON файл |
| **Пример** | `report_{command}_{run_id}.json` |
| **Зачем** | Детерминизм: один запуск → один артефакт; нет partial writes или append-mode |

### Secondary Demotion Policy

| Аспект | Описание |
|--------|----------|
| **Где** | `runtime_result_mapper._with_secondary_policy()` |
| **Реализация** | Если `secondary=True`, все errors демотируются в warnings |
| **Пример** | Ошибка shutdown при уже-failed команде → warning, не error |
| **Зачем** | Предотвращает маскировку первичной ошибки вторичными failures |

---

## 🔑 Ключевые абстракции

| Абстракция | Файл | Роль |
|------------|------|------|
| `CommandHandler` | `runtime_contracts.py` | Protocol: `(ctx, opts, report_sink) → RuntimeExecutionResult` |
| `RuntimeExecutionResult` | `runtime_contracts.py` | `TypeAlias = DomainCommandResult \| None` |
| `RuntimeErrorWithCode` | `runtime_contracts.py` | Runtime validation error с фиксированным exit code |
| `IReportRenderer` | `report_renderer.py` | Protocol: `render(envelope, report_dir, file_base_name) → str` |
| `JsonReportRenderer` | `report_renderer.py` | JSON serializer для `ReportEnvelope` |
| `ReportHandler` | `runtime.py` | Alias для `CommandHandler` |

---

## 📐 run_with_report() — lifecycle с отчётом

> Файл: `connector/delivery/cli/runtime_orchestrator.py`

Полный lifecycle выполнения CLI-команды с формированием report-артефакта.

### Шаги lifecycle

```
┌─────────────────────────────────────────────────────────┐
│  1. Load app_config, create logger, setup TeeStream     │
│  2. Create InMemoryReportContext + ReportSink            │
│  3. Create ReportAssembler                               │
│  4. Emit initial context events (CONFIG, REPORT_POLICY,  │
│     INPUT, SetMetaEvent)                                 │
├─────────────────────────────────────────────────────────┤
│  try:                                                    │
│    5. validate_requirements()                            │
│    6. create_container() + override config/transport     │
│    7. initialize_container_resources()                   │
│       → if error: apply_result_to_report(secondary=F)   │
│    8. handler(bound_ctx, opts, report_sink)              │
│       → apply_result_to_report(source="handler_result")  │
│  except SettingsLoadError/DslLoadError/                  │
│         RuntimeErrorWithCode/Exception:                  │
│    9. Build error result + apply_result_to_report()      │
├─────────────────────────────────────────────────────────┤
│  finally:                                                │
│   10. shutdown_container_resources()                     │
│       → if error: apply_result_to_report(secondary=T)   │
│   11. finalize_report_artifacts()                        │
│       → SetContextEvent(RUNTIME) + FinishEvent           │
│       → assemble() → render() → write JSON               │
│   12. Restore stdout/stderr                              │
│   13. raise typer.Exit(exit_code_from_result())          │
└─────────────────────────────────────────────────────────┘
```

### Инициализация report components (шаги 2-4)

```python
report_context = InMemoryReportContext(run_id=run_id, command=command_name)
report_sink = ReportSink(report_context)
report_assembler = ReportAssembler(context=report_context)

# Initial context events
report_sink.emit(SetContextEvent(name=ReportContextKey.CONFIG, value={"sources": sources}))
report_sink.emit(SetContextEvent(name=ReportContextKey.REPORT_POLICY, value=policy_payload))
report_sink.emit(SetContextEvent(name=ReportContextKey.INPUT, value={"csv_path": "..."}))
report_sink.emit(SetMetaEvent(items_limit=report_items_limit))
```

Report components создаются **per-command** внутри `run_with_report()`, НЕ через DI container.

### ReportPolicy resolution

```python
report_policy = ReportPolicy.from_profile(app_config.observability.report_policy_profile)
cli_include_skipped = (
    app_config.observability.report_include_skipped
    if cli_include_skipped_raw is None
    else bool(cli_include_skipped_raw)
)
effective_include_skipped_items = report_policy.resolve_include_skipped_items(cli_include_skipped)
```

Policy профиль берётся из `app_config.observability.report_policy_profile`, а `include_skipped` может быть переопределён через CLI option `--report-include-skipped`.

### items_limit resolution

```python
report_items_limit = get_opt(opts, ("report_items_limit", "items_limit"))
if report_items_limit is None:
    report_items_limit = observability.report_items_limit
report_sink.emit(SetMetaEvent(items_limit=report_items_limit))
```

CLI option имеет приоритет над config; значение фиксируется в `ReportMeta.items_limit`.

### Secondary policy в finally-блоке

```python
shutdown_result = shutdown_container_resources(...)
if shutdown_result is not None:
    apply_result_to_report(
        ..., secondary=exit_result is not None,  # secondary если handler уже вернул ошибку
    )
```

Если handler уже вернул error (`exit_result is not None`), то ошибки shutdown/finalize считаются **secondary** — их severity демотируется до warning в report.

---

## 📐 run_without_report() — lifecycle без отчёта

> Файл: `connector/delivery/cli/runtime_orchestrator.py`

Аналогичный lifecycle, но:

- Handler получает `NullReportSink()` вместо `ReportSink`
- Нет `finalize_report_artifacts()` — JSON-артефакт не создаётся
- Нет `apply_result_to_report()` — runtime errors не маппятся в report events
- stdout/stderr logging через TeeStream сохраняется

```python
exit_result = handler(bound_ctx, opts, NullReportSink())
```

Используется для команд, не требующих report (например, служебные/diagnostic команды).

---

## 🎭 runtime_result_mapper — маппинг результата в report

> Файл: `connector/delivery/cli/runtime_result_mapper.py`

### apply_runtime_result_to_report()

Основная функция маппинга `DomainCommandResult → AddItemEvent`.

**Алгоритм:**

1. **Type guard**: если `result` не `DomainCommandResult | None` → `TypeError`
2. **None check**: если `result is None` → return (no-op, success)
3. **Diagnostics extraction**:
   - Если `result.diagnostics` есть → split по severity через `_split_domain_diagnostics()` → `split_report_diagnostics()`
   - Если `not result.ok` и diagnostics нет → **synthetic diagnostic** с `primary_code` и `system_codes`
4. **Empty check**: если нет errors и нет warnings → return (no-op)
5. **Secondary policy**: если `secondary=True` → demote errors → warnings
6. **Emit**: `AddItemEvent(status=FAILED if errors else OK, meta={source, secondary, synthetic, system_codes})`

### Synthetic Diagnostic

Создаётся когда `result.ok=False` но `result.diagnostics` пуст, и `_needs_synthetic_diagnostic()` возвращает `True`:

```python
def _needs_synthetic_diagnostic(*, context: IReportContext, secondary: bool) -> bool:
    if secondary:
        return True
    summary = context.summary_snapshot()
    return summary.rows_blocked == 0 and summary.errors_total == 0
```

Логика: если отчёт уже содержит blocked rows или errors — handler result уже отражён через stage-level reporting. Synthetic нужен только если отчёт «чистый» а результат failed.

### Secondary Policy

```python
def _with_secondary_policy(*, errors, warnings, secondary: bool):
    if not secondary:
        return errors, warnings
    # Demote all errors → warnings
    downgraded = [*warnings]
    for diag in errors:
        downgraded.append(ReportDiagnostic(severity="warning", ...))
    return [], downgraded
```

### build_runtime_error_result()

Фабрика `DomainCommandResult` для runtime-исключений:

```python
def build_runtime_error_result(*, catalog, command_name, message, details=None):
    diagnostic = build_error(
        catalog=catalog,
        stage=stage_for_command(command_name),
        code="INTERNAL_ERROR",
        message=message,
        details=details,
    )
    result = DomainCommandResult()
    result.add_diagnostics([diagnostic], catalog)
    return result
```

### stage_for_command()

Маппинг runtime command name → `DiagnosticStage`:

| Command name | Stage |
|--------------|-------|
| `mapping` | `MAP` |
| `normalize` | `NORMALIZE` |
| `enrich` | `ENRICH` |
| `match` | `MATCH` |
| `resolve` | `RESOLVE` |
| `import_plan` | `PLAN` |
| `import_apply` | `APPLY` |
| `cache_refresh`, `cache_clear`, `cache_status` | `CACHE` |
| (default) | `SINK` |

Normalization: `replace("-", "_").lower()` перед lookup.

---

## 🗂️ finalize_report_artifacts() — финализация отчёта

> Файл: `connector/delivery/cli/runtime_orchestrator.py`

```python
def finalize_report_artifacts(*, report_sink, report_assembler, start_monotonic, paths,
                               log_file_path, command_name, run_id, logger, emit_user_error):
    duration_ms = getDurationMs(start_monotonic, time.monotonic())

    # 1. Emit runtime context
    report_sink.emit(SetContextEvent(
        name=ReportContextKey.RUNTIME,
        value={"log_file": log_file_path, "cache_dir": paths.cache_dir, "report_dir": paths.report_dir},
    ))

    # 2. Emit finish event
    report_sink.emit(FinishEvent(duration_ms=duration_ms))

    # 3. Assemble envelope (snapshot + enrichers)
    envelope = report_assembler.assemble()

    # 4. Render JSON artifact
    report_path = JsonReportRenderer().render(
        envelope=envelope,
        report_dir=paths.report_dir,
        file_base_name=f"report_{command_name}_{run_id}",
    )
```

Шаги:
1. Emit `SetContextEvent(RUNTIME)` — runtime paths (log, cache, report dir)
2. Emit `FinishEvent(duration_ms=...)` — фиксирует `finished_at` и `duration_ms` в meta
3. `report_assembler.assemble()` — snapshot envelope из context
4. `JsonReportRenderer().render(...)` — serialize и записать JSON файл

При ошибке финализации возвращает `result_with(SystemErrorCode.INTERNAL_ERROR)`.

---

## 📊 IReportRenderer / JsonReportRenderer

> Файл: `connector/infra/artifacts/report_renderer.py`

### Protocol

```python
@runtime_checkable
class IReportRenderer(Protocol):
    def render(self, *, envelope: ReportEnvelope, report_dir: str, file_base_name: str) -> str: ...
```

### JsonReportRenderer

```python
class JsonReportRenderer(IReportRenderer):
    def render(self, *, envelope, report_dir, file_base_name) -> str:
        Path(report_dir).mkdir(parents=True, exist_ok=True)
        report_path = str(Path(report_dir) / f"{file_base_name}.json")
        payload = asdict_envelope(envelope)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return report_path
```

- `asdict_envelope()` конвертирует `ReportEnvelope` в plain dict (deep copy via `context.asdict_envelope()`)
- UTF-8 encoding, `ensure_ascii=False` для кириллицы
- `indent=2` для human-readable output
- Возвращает абсолютный путь к записанному файлу

---

## 🚨 Exception Handling Matrix

`run_with_report()` обрабатывает следующие исключения:

| Исключение | Source label | Обработка |
|------------|-------------|-----------|
| `SettingsLoadError` | `settings_load_error` | `translate_settings_load_error()` → diagnostics → `DomainCommandResult` |
| `DslLoadError` | `dsl_load_error` | `translate_dsl_load_error()` → diagnostic → `DomainCommandResult` |
| `RuntimeErrorWithCode` | `runtime_validation_error` | `build_runtime_error_result()` с details `{runtime_exit_code, runtime_error}` |
| `Exception` (generic) | `runtime_exception` | `build_runtime_error_result()` с details `{runtime_error: class_name}` |

**Container init exceptions** (в `initialize_container_resources()`):

| Исключение | Поведение |
|------------|-----------|
| `DslLoadError` | Re-raise (обрабатывается outer handler) |
| `sqlite3.Error` | `result_with(SystemErrorCode.CACHE_ERROR)` |
| `VaultDomainError` | `result_with(SystemErrorCode.INTERNAL_ERROR)` |
| `Exception` | `result_with(SystemErrorCode.INTERNAL_ERROR)` |

**Shutdown/finalize exceptions**:

| Фаза | Поведение |
|------|-----------|
| `shutdown_container_resources` | `result_with(INTERNAL_ERROR)`, secondary=True если handler failed |
| `finalize_report_artifacts` | `result_with(INTERNAL_ERROR)`, secondary=True если handler failed |

---

## 🔌 Handler Contract

> Файл: `connector/delivery/cli/runtime_contracts.py`

```python
@runtime_checkable
class CommandHandler(Protocol):
    def __call__(
        self,
        ctx: BoundCommandContext,
        opts: Any,
        report_sink: IReportSink,
    ) -> RuntimeExecutionResult: ...
```

**Контракт:**

1. Handler всегда вызывается с **3 аргументами**: `(ctx, opts, report_sink)`
2. `report_sink` может быть `NullReportSink` в `run_without_report()`
3. Возвращает `DomainCommandResult | None`:
   - `None` → success (exit code 0)
   - `DomainCommandResult` → result.exit_code() определяет exit code
4. Handler НЕ ответственен за finalize/shutdown — это делает orchestrator
5. Handler публикует stage-level report events через `report_sink.emit(...)` напрямую или через `StageResultReporter`

---

## 🏗️ DI Wiring — report NOT in containers

Report components **не** регистрируются в DI container (`AppContainer`).

Они создаются per-command внутри `run_with_report()`:

```python
# Per-command creation (NOT in DI)
report_context = InMemoryReportContext(run_id=run_id, command=command_name)
report_sink = ReportSink(report_context)
report_assembler = ReportAssembler(context=report_context)
```

**Почему не в DI:**

- Report context привязан к конкретному command invocation, не к application scope
- Report lifecycle (create → emit → assemble → render) полностью управляется orchestrator
- Нет зависимостей на report компоненты извне orchestrator

**Как handler получает sink:**

- Через параметр `report_sink` в handler contract: `handler(ctx, opts, report_sink)`
- Handler передаёт sink в usecase → usecase создаёт `StageResultReporter` с этим sink

---

## 📊 Exit Code Contract

> Файл: `connector/delivery/cli/result_adapter.py`

### result_with()

```python
def result_with(code: SystemErrorCode) -> DomainCommandResult:
    result = DomainCommandResult()
    result.add_code(code)
    return result
```

Фабрика для runtime-ошибок с единственным system code.

### exit_code_from_result()

```python
def exit_code_from_result(result: DomainCommandResult | None) -> int:
    if result is None:
        return 0
    return result.exit_code()
```

| Ситуация | Exit code |
|----------|-----------|
| `result is None` | `0` (success) |
| `DomainCommandResult` | `result.exit_code()` — определяется `SystemErrorCode` приоритетом |
| Другой тип | `TypeError` |

---

## 📐 JSON Output Format

Формат итогового JSON-артефакта — сериализация `ReportEnvelope` через `asdict_envelope()`:

```json
{
  "meta": {
    "run_id": "abc-123",
    "command": "enrich",
    "schema_version": "2.0",
    "started_at": "2026-03-03T12:00:00",
    "finished_at": "2026-03-03T12:00:05",
    "duration_ms": 5000,
    "items_limit": 500,
    "items_stored": 42,
    "items_truncated": false
  },
  "summary": {
    "status": "FAILED",
    "rows_total": 1000,
    "rows_passed": 950,
    "rows_blocked": 45,
    "rows_skipped": 5,
    "errors_total": 45,
    "warnings_total": 12,
    "ops": {
      "TRANSFORM": {"ok": 950, "failed": 45, "count": 1000}
    }
  },
  "context": {
    "CONFIG": {"sources": ["settings.yaml"]},
    "REPORT_POLICY": {"profile": "STANDARD", "...": "..."},
    "INPUT": {"csv_path": "employees.csv"},
    "STAGE": {"stage": "ENRICH", "strategy": "TransformStageReportStrategy"},
    "RUNTIME": {"log_file": "/logs/enrich_abc-123.log", "...": "..."}
  },
  "items": [
    {
      "status": "FAILED",
      "row_ref": {"row_number": 42, "employee_id": "E001"},
      "payload": {"field": "value"},
      "errors": [{"severity": "error", "stage": "ENRICH", "code": "VALIDATION_ERROR", "...": "..."}],
      "warnings": [],
      "meta": {}
    }
  ]
}
```

Путь файла: `{report_dir}/report_{command}_{run_id}.json`

---

## 🔄 Interactions

### Report delivery → Report domain

| Вызов | Описание |
|-------|----------|
| `InMemoryReportContext(run_id, command)` | Создание scoped context |
| `ReportSink(context)` | Создание sink для context |
| `ReportAssembler(context)` | Создание assembler для context |
| `report_sink.emit(SetContextEvent(...))` | Публикация context блоков |
| `report_sink.emit(SetMetaEvent(...))` | Установка items_limit |
| `report_sink.emit(FinishEvent(...))` | Финализация meta |
| `report_assembler.assemble()` | Сборка envelope snapshot |

### Report delivery → Report renderer

| Вызов | Описание |
|-------|----------|
| `JsonReportRenderer().render(envelope, report_dir, file_base_name)` | Сериализация и запись |

### Report delivery → Result domain

| Вызов | Описание |
|-------|----------|
| `apply_runtime_result_to_report(sink, context, result, ...)` | Result → report event |
| `build_runtime_error_result(catalog, command_name, message, details)` | Exception → `DomainCommandResult` |
| `result_with(SystemErrorCode)` | Фабрика result с system code |
| `exit_code_from_result(result)` | Result → OS exit code |

---

## 📌 Contracts

### Handler → Orchestrator

1. Handler возвращает `DomainCommandResult | None`
2. Handler НЕ управляет report lifecycle (create/finalize)
3. Handler публикует stage events через `report_sink.emit()`

### Orchestrator → Report Domain

1. `InMemoryReportContext` создаётся per-command, не shared
2. `ReportSink.emit()` — единственный ingestion API
3. `FinishEvent` эмитится строго один раз перед `assemble()`
4. Context events (CONFIG, REPORT_POLICY, INPUT, RUNTIME) эмитятся orchestrator

### Result Mapper → Report Domain

1. Input — только `DomainCommandResult | None`; другие типы → `TypeError`
2. `secondary=True` → все errors демотируются до warnings
3. Synthetic diagnostic создаётся только если report ещё не содержит errors/blocked rows

---

## 💡 Scenarios

### Сценарий 1: Успешное выполнение команды

1. `run_with_report()` создаёт context/sink/assembler
2. Handler выполняется, публикует stage events, возвращает `None`
3. `apply_result_to_report(result=None)` → no-op
4. `finalize_report_artifacts()` → emit RUNTIME + Finish → assemble → render JSON
5. Exit code: `0`

### Сценарий 2: Handler возвращает failed result

1. Handler возвращает `DomainCommandResult` с diagnostics
2. `apply_result_to_report(secondary=False)` → emit `AddItemEvent(status=FAILED)`
3. Shutdown → `apply_result_to_report(secondary=True)` если shutdown тоже failed
4. Finalize → JSON содержит handler errors + (опционально) demoted shutdown warnings
5. Exit code: `result.exit_code()` от handler result

### Сценарий 3: Runtime exception до handler

1. `validate_requirements()` или `initialize_container_resources()` бросает exception
2. Exception handler создаёт `DomainCommandResult` через `build_runtime_error_result()`
3. `apply_result_to_report(secondary=False)` → emit error item
4. Finally: shutdown (safe) + finalize → JSON содержит runtime error
5. Exit code: определяется error result

### Сценарий 4: run_without_report

1. Handler получает `NullReportSink()` — все `emit()` → no-op
2. Нет finalize/render — JSON файл не создаётся
3. Errors выводятся только в stderr и logs
4. Exit code: определяется handler result

---

## ⚠️ Failure Modes

| Ситуация | Поведение | Как обрабатывать |
|----------|-----------|------------------|
| Handler throws exception | Catch в orchestrator, build error result, apply to report | Проверить logs и report JSON |
| Container init fails | `result_with(CACHE_ERROR/INTERNAL_ERROR)`, handler не вызывается | Проверить DI configuration |
| Shutdown fails после handler error | Secondary demotion: errors → warnings | Primary error сохраняется, shutdown warning в items |
| Report finalization fails | `result_with(INTERNAL_ERROR)`, JSON может не быть записан | Проверить log file |
| Invalid result type от handler | `TypeError` propagates, caught by generic Exception handler | Fix handler to return `DomainCommandResult \| None` |
| `SettingsLoadError` | Diagnostics через `translate_settings_load_error()` | Проверить settings YAML |
| `DslLoadError` | Diagnostics через `translate_dsl_load_error()` | Проверить DSL spec файлы |

---

## 🔑 Invariants

1. **Per-command report scope**: один `InMemoryReportContext` + `ReportSink` на вызов команды; никогда не shared между командами.
2. **Single handler invocation**: handler вызывается не более одного раза; retry — ответственность вызывающего кода.
3. **Guaranteed finalize**: `finalize_report_artifacts()` выполняется в `finally` блоке — даже при exception handler.
4. **Secondary ordering**: shutdown и finalize results всегда secondary если handler уже вернул error.
5. **Type safety**: runtime result mapper принимает только `DomainCommandResult | None`; другие типы → `TypeError`.
6. **Single FinishEvent**: `FinishEvent` эмитится ровно один раз, непосредственно перед `assemble()`.
7. **Stdout/stderr restoration**: оригинальные streams восстанавливаются в inner `finally` блоке.

---

## ⏱️ Performance Notes

- Report context/sink/assembler — lightweight объекты; создание per-command не создаёт overhead
- `JsonReportRenderer.render()` выполняет `json.dump()` с `indent=2` — для больших отчётов (10k+ items) может занять сотни миллисекунд
- `asdict_envelope()` выполняет `deepcopy()` — аллоцирует полную копию envelope перед сериализацией
- TeeStream перехватывает stdout/stderr для дублирования в log файл; при intensive print output может добавить latency

---

## 🛠️ Extension Guide

### Добавить новый формат рендеринга

1. Реализовать `IReportRenderer` protocol:
   ```python
   class HtmlReportRenderer(IReportRenderer):
       def render(self, *, envelope, report_dir, file_base_name) -> str:
           ...
   ```
2. Использовать в `finalize_report_artifacts()` вместо `JsonReportRenderer()`

### Добавить новый runtime context block

1. Добавить `ReportContextKey` в `contracts.py` (см. [report-models.md](report-models.md))
2. Emit `SetContextEvent(name=key, value=payload)` в нужной фазе orchestrator

### Добавить новый тип runtime exception

1. Создать handler в `run_with_report()`:
   ```python
   except MyNewError as exc:
       exit_result = build_runtime_error_result(...)
       apply_result_to_report(..., source="my_error", secondary=False)
   ```
2. Или обработать в `initialize_container_resources()` если ошибка при init

### Добавить команду без report

Использовать `run_without_report()` — handler получит `NullReportSink`.

---

## 🔗 Связанные документы

- [Report models](report-models.md) — события, context, sink, assembler, policy
- [Report pipeline](report-pipeline.md) — stage adapters, StageResultReporter, strategies
- [Report architecture issues](report-architecture-issues.md) — проблемы и решения
- [REPORT-DEC-001](../../adr/report/REPORT-DEC-001-execution-context-event-driven-report-layer.md) — event-driven architecture
- [REPORT-DEC-005](../../adr/report/REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md) — runtime orchestrator decomposition
- [REPORT-DEC-008](../../adr/report/REPORT-DEC-008-report-policy-capability-profiles-and-contract.md) — ReportPolicy capability profiles
