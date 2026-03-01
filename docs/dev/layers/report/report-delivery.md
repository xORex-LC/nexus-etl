# Report Delivery — CLI Lifecycle, I/O, and Wiring

> **Run lifecycle**: `run_with_report()` wraps every CLI command — creates the `ReportCollector`, calls the handler, finalizes artifacts, writes JSON, and maps the result to an OS exit code.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [📊 report_writer — I/O функции](#-report_writer--io-функции)
  - [createEmptyReport()](#createemptyreport)
  - [finalizeReport()](#finalizereport)
  - [writeReportJson()](#writereportjson)
- [📊 run_with_report() — полный lifecycle](#-run_with_report--полный-lifecycle)
  - [Инициализация](#инициализация)
  - [_call_handler() — dispatch по сигнатуре](#_call_handler--dispatch-по-сигнатуре)
  - [_apply_cli_result_to_report()](#_apply_cli_result_to_report)
  - [_finalize_report_artifacts()](#_finalize_report_artifacts)
  - [Завершение и exit code](#завершение-и-exit-code)
- [📊 run_without_report()](#-run_without_report)
- [📊 _stage_for_command()](#-_stage_for_command)
- [🗂️ JSON output — формат файла](#️-json-output--формат-файла)
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

**Назначение**: Оркестрировать lifecycle выполнения CLI-команды — от создания отчёта до записи JSON-артефакта на диск и возврата exit code.

**Ключевая ответственность**:
- `createEmptyReport()` — создать `ReportCollector` с первичным context-блоком `"config"`.
- `finalizeReport()` — проставить runtime-метаданные и вызвать `report.finish()`.
- `writeReportJson()` — сериализовать `ReportEnvelope` в JSON-файл.
- `run_with_report()` — оркестрировать весь lifecycle: init DI → create report → call handler → finalize → write → shutdown DI → exit code.
- `run_without_report()` — то же, но без отчёта (для административных команд).
- `_call_handler()` — dispatch по количеству параметров handler (2-param vs. 3-param с report).
- `_exit_code_from_result()` — сопоставить `CommandResult.status` с OS exit code.

**Расположение в кодовой базе**:
- `connector/infra/artifacts/report_writer.py` — три I/O функции
- `connector/delivery/cli/runtime.py` — `run_with_report()`, `run_without_report()` и все вспомогательные функции
- `connector/domain/diagnostics/command_result.py` — `CommandResult`
- `connector/domain/diagnostics/policies.py` — `SystemErrorCode`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/
├── infra/
│   └── artifacts/
│       └── report_writer.py          # createEmptyReport(), finalizeReport(), writeReportJson()
├── delivery/
│   └── cli/
│       ├── runtime.py                # run_with_report(), run_without_report(), helpers
│       └── containers.py            # DI containers (ReportCollector НЕ регистрируется)
└── domain/
    └── diagnostics/
        ├── command_result.py         # CommandResult (ok | warn | error)
        └── policies.py              # SystemErrorCode enum
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Sequence | [Sequence Diagram](../../../uml/pipeline/report_layer/report_layer_sequence.puml) | Полный lifecycle run_with_report() |
| Activity | [Activity Diagram](../../../uml/pipeline/report_layer/report_layer_activity.puml) | Алгоритм обработки command + report |
| Components | [Component Diagram](../../../uml/pipeline/report_layer/report_layer_components.puml) | Зависимости между компонентами |

**PlantUML исходники**: `docs/uml/pipeline/report_layer/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Template Method (Жизненный цикл)

**Где применяется**: `run_with_report()` определяет фиксированную последовательность шагов lifecycle (init → report → handler → finalize → cleanup → exit_code), каждый из которых делегируется helper-функции.

**Реализация в коде**:
- `run_with_report()` в `connector/delivery/cli/runtime.py` — orchestrator
- `_initialize_container_resources()`, `_call_handler()`, `_finalize_report_artifacts()`, `_shutdown_container_resources()` — шаги lifecycle

**Зачем**: Единый lifecycle для всех команд с отчётом; новая команда добавляется через handler, а не через изменение lifecycle.

---

#### Паттерн 2: Strategy через signature inspection

**Где применяется**: `_call_handler()` использует `inspect.signature()` для определения, принимает ли handler `report` как третий аргумент. Это позволяет поддерживать старые 2-param обработчики рядом с новыми 3-param.

**Реализация в коде**:
- `_call_handler()` в `connector/delivery/cli/runtime.py`

**Зачем**: Backward-compatible API для command handlers; не требует переписывать все существующие обработчики при добавлении report-параметра.

---

#### Паттерн 3: Write-once artifact

**Где применяется**: `writeReportJson()` создаёт JSON-файл один раз по завершении прогона. Файл не обновляется инкрементально — это атомарная запись финального состояния.

**Зачем**: Детерминированный артефакт; внешние системы могут читать файл только после полного завершения команды.

### Диаграмма зависимостей

```
CLI command entry point
        │
        ▼
run_with_report(command, args, handler, container)
        │
        ├─ createEmptyReport()  ────────────────► ReportCollector (new instance)
        │      └─ set_context("config", ...)
        │
        ├─ _initialize_container_resources()  ──► DI resources (vault, sqlite, ...)
        │
        ├─ _call_handler(handler, args, container, report)
        │      ├─ 3-param: handler(args, container, report)
        │      └─ 2-param: handler(args, container)
        │              │ returns CommandResult | None
        │
        ├─ _apply_cli_result_to_report(result, report, command)
        │
        ├─ _finalize_report_artifacts(report, args, result)
        │      ├─ finalizeReport()   ──────────► report.finish() + context["runtime"]
        │      └─ writeReportJson()  ──────────► {report_dir}/{run_id}.json
        │
        ├─ _shutdown_container_resources()
        │
        └─ _exit_code_from_result(result)  ──────► int (0 or 1)
```

---

## 🔑 Ключевые абстракции

### Основные функции

| Функция | Модуль | Назначение |
|---------|--------|-----------|
| `createEmptyReport(runId, command, configSources)` | `report_writer.py` | Создаёт ReportCollector с базовым config-контекстом |
| `finalizeReport(report, durationMs, logFile, cacheDir, reportDir)` | `report_writer.py` | Проставляет runtime-контекст и финализирует collector |
| `writeReportJson(report, reportDir, fileBaseName)` | `report_writer.py` | Сериализует envelope в JSON-файл |
| `run_with_report(command, args, handler, container)` | `runtime.py` | Полный lifecycle с отчётом |
| `run_without_report(command, args, handler, container)` | `runtime.py` | Lifecycle без отчёта (для admin команд) |
| `_call_handler(handler, args, container, report)` | `runtime.py` | Dispatch по сигнатуре handler |
| `_stage_for_command(command_name)` | `runtime.py` | Маппинг имени команды → DiagnosticStage |
| `_exit_code_from_result(result)` | `runtime.py` | CommandResult.status → int exit code |

### CommandResult

**Модуль**: `connector/domain/diagnostics/command_result.py`

```python
@dataclass
class CommandResult:
    status: CommandStatus = "ok"          # "ok" | "warn" | "error"
    stats: dict[str, int] = field(...)
    items: list[dict[str, Any]] = field(...)
    errors: list[DiagnosticItem] = field(...)
    warnings: list[DiagnosticItem] = field(...)
```

`CommandResult` — легковесный объект результата, не связанный с I/O и форматированием отчёта. Возвращается всеми command handlers и используется для:
1. Добавления CLI-level диагностики в `ReportCollector`.
2. Определения exit code.

**`add_code(SystemErrorCode)`**: Эскалирует `status` на основе кода ошибки:
- `SystemErrorCode.OK` → статус остаётся `"ok"`
- `SystemErrorCode.DATA_INVALID` → эскалирует до `"error"`
- `SystemErrorCode.INTERNAL_ERROR` → эскалирует до `"error"`
- `SystemErrorCode.CACHE_ERROR` → эскалирует до `"error"`

---

## 📊 report_writer — I/O функции

**Модуль**: `connector/infra/artifacts/report_writer.py`

Три функции, отвечающие за создание, финализацию и запись артефакта отчёта. Намеренно минимальны — вся бизнес-логика в `ReportCollector`.

### createEmptyReport()

**Сигнатура**:
```python
def createEmptyReport(
    runId: str,
    command: str,
    configSources: list[str],
) -> ReportCollector:
```

**Назначение**: Создать свежий `ReportCollector` для нового запуска команды.

**Алгоритм**:
```python
def createEmptyReport(runId, command, configSources):
    report = ReportCollector(
        run_id=runId,
        command=command,
        started_at=datetime.now(tz=timezone.utc),
    )
    report.set_context("config", {"config_sources": configSources})
    return report
```

**Что устанавливает**:
- `run_id` — уникальный идентификатор запуска (из CLI args или сгенерированный)
- `command` — имя CLI-команды (`"import"`, `"apply"`, `"enrich"`, etc.)
- `started_at` — UTC timestamp начала
- `context["config"]` — пути к конфиг-файлам (из `AppConfig`)

---

### finalizeReport()

**Сигнатура**:
```python
def finalizeReport(
    report: ReportCollector,
    durationMs: int,
    logFile: str | None,
    cacheDir: str | None,
    reportDir: str | None,
) -> None:
```

**Назначение**: Добавить runtime-метаданные в контекст и вызвать `report.finish()`.

**Алгоритм**:
```python
def finalizeReport(report, durationMs, logFile, cacheDir, reportDir):
    report.set_context("runtime", {
        "duration_ms": durationMs,
        "log_file": logFile,
        "cache_dir": cacheDir,
        "report_dir": reportDir,
    })
    report.finish()
```

**Что устанавливает**:
- `context["runtime"]` — технические параметры запуска (длительность, пути к логам и директориям)
- `finish()` — фиксирует `finished_at` и `duration_ms` в `ReportMeta`

**Когда вызывается**: В `_finalize_report_artifacts()` после завершения handler, непосредственно перед `writeReportJson()`.

---

### writeReportJson()

**Сигнатура**:
```python
def writeReportJson(
    report: ReportCollector,
    reportDir: str,
    fileBaseName: str,
) -> str:
```

**Назначение**: Сериализовать финальный `ReportEnvelope` в JSON-файл и вернуть путь.

**Алгоритм**:
```python
def writeReportJson(report, reportDir, fileBaseName):
    envelope = report.build()               # → ReportEnvelope (финальный снимок)
    data = asdict_report(envelope)          # → dict (глубокая сериализация)
    path = os.path.join(reportDir, f"{fileBaseName}.json")
    os.makedirs(reportDir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
```

**Детали**:
- `fileBaseName` обычно равен `run_id` (или `{command}-{run_id}`)
- `reportDir` берётся из `AppConfig.paths.reports_dir`
- Директория создаётся при необходимости (`makedirs(exist_ok=True)`)
- Encoding: UTF-8, `ensure_ascii=False` — русские символы хранятся как есть
- Indent: 2 пробела — человекочитаемый формат

---

## 📊 run_with_report() — полный lifecycle

**Модуль**: `connector/delivery/cli/runtime.py`

Главная оркестрирующая функция для всех команд с отчётностью.

**Сигнатура**:
```python
def run_with_report(
    command: str,
    args: Any,
    handler: Callable,
    container: Any,
) -> int:   # OS exit code
```

### Инициализация

```
1. configSources = _extract_config_sources(args)
   report = createEmptyReport(runId=args.run_id, command=command, configSources=configSources)

2. _initialize_container_resources(container)
   → Вызывает eager init DI-ресурсов:
     - SqliteContainer.vault_ready → VaultStartupGuard.ensure_ready()
     - Другие Resource-провайдеры, если объявлены
```

### _call_handler() — dispatch по сигнатуре

**Назначение**: Вызвать handler с правильным набором аргументов в зависимости от его сигнатуры.

**Алгоритм**:
```python
def _call_handler(handler, args, container, report):
    sig = inspect.signature(handler)
    params = [
        p for p in sig.parameters.values()
        if p.name != "self"
    ]
    if len(params) >= 3:
        # Новый стиль: handler(args, container, report)
        return handler(args, container, report)
    else:
        # Legacy: handler(args, container)
        return handler(args, container)
```

**Два режима**:

| Количество параметров | Вызов | Применение |
|-----------------------|-------|-----------|
| ≥ 3 (args, container, report) | `handler(args, container, report)` | Современные обработчики с отчётом |
| 2 (args, container) | `handler(args, container)` | Legacy-обработчики без report |

**Backward compatibility**: Старые handlers продолжают работать без изменений — `run_with_report()` всё равно создаёт и финализирует отчёт, просто handler не получает ссылку на collector.

---

### _apply_cli_result_to_report()

**Назначение**: Перенести диагностику из `CommandResult` (CLI-level ошибки) в `ReportCollector`.

```python
def _apply_cli_result_to_report(result, report, command):
    if result is None:
        return
    stage = _stage_for_command(command)
    for error in result.errors:
        report.add_item(
            status="FAILED",
            row_ref=None,
            payload=None,
            errors=to_report_diagnostics([error], None),
            warnings=[],
            meta={"stage": stage},
            store=True,
        )
    for warning in result.warnings:
        report.add_item(
            status="OK",
            row_ref=None,
            payload=None,
            errors=[],
            warnings=to_report_diagnostics(None, [warning]),
            meta={"stage": stage},
            store=True,
        )
```

**Назначение**: CLI-level ошибки (например, vault startup failure, cache error) становятся `ReportItem` без `row_ref` и `payload`. Это позволяет видеть их в `envelope.items` и в `summary.by_stage`.

---

### _finalize_report_artifacts()

**Алгоритм**:
```python
def _finalize_report_artifacts(report, args, result):
    duration_ms = _compute_duration(report)
    finalizeReport(
        report=report,
        durationMs=duration_ms,
        logFile=getattr(args, "log_file", None),
        cacheDir=getattr(args, "cache_dir", None),
        reportDir=getattr(args, "report_dir", None),
    )
    report_dir = getattr(args, "report_dir", None)
    if report_dir:
        file_base = getattr(args, "run_id", "report")
        writeReportJson(report, report_dir, file_base)
```

**Порядок**: `finalizeReport()` всегда вызывается до `writeReportJson()`. Это гарантирует, что `context["runtime"]` и `meta.finished_at` присутствуют в JSON-файле.

---

### Завершение и exit code

**`_exit_code_from_result(result) → int`**:

```python
def _exit_code_from_result(result: CommandResult | None) -> int:
    if result is None:
        return 0
    if result.status == "error":
        return 1
    return 0  # "ok" или "warn"
```

**Таблица маппинга**:

| CommandResult.status | Exit code | Значение |
|---------------------|-----------|---------|
| `"ok"` | 0 | Успешное выполнение |
| `"warn"` | 0 | Выполнено с предупреждениями (не ошибка) |
| `"error"` | 1 | Ошибка выполнения |
| `None` (handler вернул None) | 0 | Трактуется как успех |

**Замечание**: `"warn"` → 0 намеренно — предупреждения не прерывают CI/CD pipeline. Ошибки данных (`DATA_INVALID`) → `"error"` → exit code 1.

---

### Полный lifecycle run_with_report() — пошагово

```
┌─────────────────────────────────────────────────────────────────┐
│                    run_with_report()                            │
│                                                                 │
│  1. createEmptyReport()          → report (ReportCollector)     │
│     └─ set_context("config", ...)                               │
│                                                                 │
│  2. _initialize_container_resources(container)                  │
│     └─ vault_ready.init() → VaultStartupGuard.ensure_ready()   │
│                                                                 │
│  3. _call_handler(handler, args, container, report)             │
│     ├─ 3-param: handler(args, container, report) → result       │
│     └─ 2-param: handler(args, container) → result               │
│                                                                 │
│  4. _apply_cli_result_to_report(result, report, command)        │
│     └─ CLI-level errors → report.add_item(store=True)           │
│                                                                 │
│  5. _finalize_report_artifacts(report, args, result)            │
│     ├─ finalizeReport() → set_context("runtime") + finish()    │
│     └─ writeReportJson() → {report_dir}/{run_id}.json           │
│                                                                 │
│  6. _shutdown_container_resources(container)                    │
│                                                                 │
│  7. return _exit_code_from_result(result)   → 0 | 1            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 run_without_report()

**Сигнатура**:
```python
def run_without_report(
    command: str,
    args: Any,
    handler: Callable,
    container: Any,
) -> int:
```

**Назначение**: Lifecycle для команд, которые не производят JSON-отчёт (административные команды: cache invalidate, schema migrate, diagnostics).

**Отличия от `run_with_report()`**:
- Не создаётся `ReportCollector`.
- Не вызываются `finalizeReport()` и `writeReportJson()`.
- Handler всегда вызывается в 2-param режиме: `handler(args, container)`.
- DI init/shutdown выполняются так же.

**Алгоритм**:
```
1. _initialize_container_resources(container)
2. result = handler(args, container)
3. _shutdown_container_resources(container)
4. return _exit_code_from_result(result)
```

**Когда использовать**: Когда команда не обрабатывает строки датасета и не создаёт отчёт — например, `cache refresh --dry-run`, `vault probe`, `schema check`.

---

## 📊 _stage_for_command()

**Назначение**: Сопоставить имя CLI-команды с `DiagnosticStage`, чтобы CLI-level ошибки в `_apply_cli_result_to_report()` получили корректную stage-атрибуцию.

**Маппинг** (типичный):

| command | DiagnosticStage |
|---------|----------------|
| `"import"` | `DiagnosticStage.MAP` |
| `"enrich"` | `DiagnosticStage.ENRICH` |
| `"apply"` | `DiagnosticStage.APPLY` |
| `"cache_refresh"` | `DiagnosticStage.CACHE` |
| (default/unknown) | `DiagnosticStage.MAP` |

**Реализация**:
```python
def _stage_for_command(command_name: str) -> DiagnosticStage:
    mapping = {
        "import": DiagnosticStage.MAP,
        "enrich": DiagnosticStage.ENRICH,
        "apply": DiagnosticStage.APPLY,
        "cache_refresh": DiagnosticStage.CACHE,
    }
    return mapping.get(command_name, DiagnosticStage.MAP)
```

---

## 🗂️ JSON output — формат файла

**Расположение**: `{AppConfig.paths.reports_dir}/{run_id}.json`

**Кодировка**: UTF-8, indent=2, ensure_ascii=False

**Пример полного файла**:

```json
{
  "status": "PARTIAL",
  "meta": {
    "run_id": "a3f7c2d1-1234-5678-abcd-ef0123456789",
    "dataset": "employees",
    "command": "import",
    "started_at": "2026-02-27T10:00:00+00:00",
    "finished_at": "2026-02-27T10:00:05+00:00",
    "duration_ms": 5123,
    "items_limit": 1000,
    "items_truncated": false,
    "app_version": "1.2.0",
    "git_rev": "abc1234def5678"
  },
  "summary": {
    "rows_total": 250,
    "rows_passed": 247,
    "rows_blocked": 3,
    "rows_with_warnings": 12,
    "errors_total": 3,
    "warnings_total": 15,
    "by_stage": {
      "ENRICH": 2,
      "MATCH": 1
    },
    "ops": {
      "create": {"ok": 200, "failed": 0, "count": 200},
      "update": {"ok": 47, "failed": 3, "count": 50},
      "skip": {"ok": 0, "failed": 0, "count": 0},
      "apply_failed": {"ok": 0, "failed": 3, "count": 3}
    }
  },
  "items": [
    {
      "status": "FAILED",
      "row_ref": {
        "line_no": 42,
        "row_id": "row-042",
        "identity_primary": "employee_id",
        "identity_value": "E0042"
      },
      "payload": {
        "employee_id": "E0042",
        "name": "Alice Smith",
        "department": "Engineering",
        "password": "***"
      },
      "diagnostics": [
        {
          "severity": "error",
          "stage": "ENRICH",
          "code": "secret_store_failed",
          "field": "password",
          "message": "Failed to store secret for field 'password'",
          "rule": null,
          "details": {"reason": "vault_not_ready"}
        }
      ],
      "meta": {
        "match_key": "E0042",
        "secret_candidate_fields": ["password"],
        "upstream_errors_count": 0,
        "upstream_warnings_count": 0
      }
    }
  ],
  "context": {
    "config": {
      "config_sources": ["/etc/ankey/app.yaml"]
    },
    "input": {
      "dataset": "employees",
      "source_file": "data/employees.csv",
      "record_count": 250
    },
    "enrich": {
      "vault_rollout": {
        "mode": "canary",
        "triggered": true,
        "reason": "canary_bucket_in_range"
      }
    },
    "apply": {
      "plan_path": "plans/run-a3f7c2d1.json",
      "dry_run": false,
      "target": "ankey_rest",
      "retries": 3
    },
    "runtime": {
      "duration_ms": 5123,
      "log_file": "logs/run-a3f7c2d1.log",
      "cache_dir": "cache/",
      "report_dir": "reports/"
    }
  }
}
```

### Структура top-level полей

| Поле | Тип | Всегда присутствует | Описание |
|------|-----|---------------------|---------|
| `status` | `string` | Да | `"SUCCESS"` / `"PARTIAL"` / `"FAILED"` |
| `meta` | `object` | Да | Метаданные запуска |
| `summary` | `object` | Да | Агрегированные счётчики |
| `items` | `array` | Да (может быть `[]`) | Детализация по строкам (ограничена `items_limit`) |
| `context` | `object` | Да (может быть `{}`) | Именованные блоки от стадий |

### Специальные значения

- `"password": "***"` — явно замаскированное секретное поле
- `"items_truncated": true` — список items обрезан по `items_limit`; счётчики в summary полные
- `"row_ref": null` — CLI-level ошибка без привязки к строке (например, vault startup failure)
- `"payload": null` — item без payload (например, строка без `should_store` или CLI-level item)

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| DI Container (`containers.py`) | Инициализирует / завершает | `_initialize_container_resources()`, `_shutdown_container_resources()` | Eager init vault, sqlite; graceful shutdown |
| ReportCollector (domain/reporting) | Создаёт и передаёт | `createEmptyReport()` → коллектор через handler | Collector живёт в lifecycle wrapper, не в DI |
| Command handlers (delivery/commands) | Вызывает | `_call_handler()` | Handler мутирует collector и возвращает CommandResult |
| VaultStartupGuard | Зависит через DI | `container.vault.vault_ready.init()` | Fail-fast если vault не готов |
| AppConfig | Читает пути | `args.report_dir`, `args.log_file`, `args.cache_dir` | Для finalizeReport и writeReportJson |
| OS filesystem | Пишет | `writeReportJson()` → `open()` | JSON-артефакт на диске |

---

## 🔌 Контракты и границы

### DI wiring — ReportCollector НЕ регистрируется

`ReportCollector` намеренно не является DI-managed сервисом:

```python
# ❌ Этого НЕТ в containers.py:
class ReportContainer(containers.DeclarativeContainer):
    collector = providers.Singleton(ReportCollector)  # НЕВЕРНО
```

```python
# ✅ Что реально происходит в runtime.py:
def run_with_report(command, args, handler, container):
    report = createEmptyReport(...)    # создаётся локально
    result = _call_handler(handler, args, container, report)  # передаётся явно
```

**Причины**:
1. `ReportCollector` stateful и per-invocation — Singleton не подходит.
2. Factory-provider создавал бы новый collector при каждом `()` — нужна передача одного экземпляра.
3. Явная передача через параметр делает зависимость видимой и тестируемой.

### Контракт handler функций

**3-param handler** (современный стиль):
```python
def handle_import(args: ImportArgs, container: AppContainer, report: ReportCollector) -> CommandResult:
    # report доступен для set_context(), add_item() и т.д.
    ...
```

**2-param handler** (legacy стиль):
```python
def handle_cache_refresh(args: CacheArgs, container: AppContainer) -> CommandResult:
    # report недоступен; report создаётся и финализируется runtime'ом без участия handler
    ...
```

### Контракт createEmptyReport / finalizeReport / writeReportJson

```
createEmptyReport() → report (незавершённый)
     │
     │ (handler мутирует report)
     ▼
finalizeReport(report, ...) → report (завершённый, finish() вызван)
     │
     ▼
writeReportJson(report, ...) → файл на диске
```

**Нарушение порядка**: вызов `writeReportJson()` до `finalizeReport()` → `meta.finished_at == null`, `meta.duration_ms == null` в файле.

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `runtime.py` → `report_writer.py` (delivery → infra artifacts)
- ✅ `runtime.py` → `ReportCollector` (delivery → domain)
- ✅ `runtime.py` → `CommandResult` (delivery → domain diagnostics)
- ✅ `report_writer.py` → `ReportCollector` (infra → domain)

**Запрещённые зависимости**:
- ❌ `ReportCollector` → `runtime.py` — домен не знает про delivery
- ❌ `report_writer.py` → DI containers — инфраструктура I/O не зависит от DI
- ❌ Command handlers → `runtime.py` напрямую — handlers вызываются через `_call_handler()`, не вызывают runtime самостоятельно

---

## 💡 Типичные сценарии

### Сценарий 1: Стандартный import с отчётом

```python
# Регистрация команды в CLI:
@app.command("import")
def import_command(args: ImportArgs):
    container = build_container(args)
    exit_code = run_with_report(
        command="import",
        args=args,
        handler=handle_import,         # 3-param handler
        container=container,
    )
    raise typer.Exit(code=exit_code)

# Handler (3-param):
def handle_import(args: ImportArgs, container: AppContainer, report: ReportCollector) -> CommandResult:
    report.set_meta(dataset=args.dataset, app_version=APP_VERSION, git_rev=GIT_REV)
    report.set_context("input", {"dataset": args.dataset, "source_file": args.source})

    processor = TransformResultProcessor(
        report=report,
        include_items=args.include_items,
        context_key="normalize",
        ...
    )
    for result in run_normalize_pipeline(args):
        processor.process(result)
    return processor.finalize()
```

---

### Сценарий 2: Vault startup failure — отчёт содержит CLI-level ошибку

```
run_with_report("import", args, handler, container)
    │
    ├─ _initialize_container_resources(container)
    │      └─ vault_ready.init() → VaultStartupGuard.ensure_ready()
    │              └─ VaultStartupKeyValidationError("active key missing")
    │
    ├─ vault_startup_error_result(exc) → CommandResult(status="error", errors=[diag])
    │
    ├─ _apply_cli_result_to_report(result, report, "import")
    │      └─ report.add_item(
    │             status="FAILED", row_ref=None, payload=None,
    │             errors=[ReportDiagnostic(stage="MAP", code="VAULT_KEY_MISSING", ...)],
    │             store=True,
    │         )
    │
    ├─ _finalize_report_artifacts() → JSON файл записан
    │
    └─ exit code = 1
```

В JSON-файле появится item без `row_ref` и без `payload` — маркер CLI-level отказа:
```json
{
  "items": [
    {
      "status": "FAILED",
      "row_ref": null,
      "payload": null,
      "diagnostics": [{"severity": "error", "stage": "MAP", "code": "VAULT_KEY_MISSING", ...}],
      "meta": {"stage": "MAP"}
    }
  ]
}
```

---

### Сценарий 3: Dry-run apply без записи JSON

```python
# Команда без report_dir → writeReportJson не вызывается
args.report_dir = None

run_with_report("apply", args, handle_apply, container)
# _finalize_report_artifacts():
#   finalizeReport() → вызывается всегда
#   writeReportJson() → ПРОПУСКАЕТСЯ (report_dir is None)
```

Даже без записи файла `finalizeReport()` всегда вызывается — `finish()` выполняется, таймстамп фиксируется.

---

### Сценарий 4: Legacy 2-param handler

```python
def handle_cache_admin(args: CacheArgs, container: AppContainer) -> CommandResult:
    # Нет параметра report — не получает collector
    cache = container.cache_admin()
    cache.invalidate(args.dataset)
    result = CommandResult()
    result.add_code(SystemErrorCode.OK)
    return result

exit_code = run_with_report("cache_admin", args, handle_cache_admin, container)
# _call_handler() обнаруживает 2 параметра → handler(args, container)
# report создаётся и финализируется runtime'ом, handler его не видит
# В отчёте: только context["config"] и context["runtime"]
```

---

## 📌 Важные детали

### Особенности реализации

- **`_call_handler()` через inspect.signature()**: Рефлексия вызывается один раз на invocation — не является bottleneck. Параметры подсчитываются без учёта `self`.
- **`_initialize_container_resources()` eagerly**: Все `Resource`-провайдеры DI инициализируются до вызова handler. Если vault startup guard упал — handler не вызывается.
- **`_shutdown_container_resources()` всегда вызывается**: Даже если handler бросил исключение (через try/finally). Это гарантирует корректное закрытие соединений.
- **Отчёт пишется всегда**: Даже при `CommandResult.status == "error"` — JSON-файл создаётся. Это позволяет отлаживать прогоны с ошибками.
- **`report_dir=None` → JSON не пишется**: Если `args.report_dir` не задан (например, в unit-тестах или при явном `--no-report`), `writeReportJson()` пропускается.

### 🚨 Failure Modes

| Ситуация | Поведение | Как обработать |
|----------|-----------|---------------|
| Handler бросает необработанное исключение | Исключение всплывает; `_shutdown_container_resources()` вызывается в finally; отчёт НЕ пишется | Не допускать исключений из handler — возвращать `CommandResult(status="error")` |
| `writeReportJson()` — ошибка I/O (нет прав, диск полон) | Исключение всплывает; exit code не возвращается | Убедиться в наличии прав на `report_dir`; проверить disk space |
| `_initialize_container_resources()` — vault startup failure | `VaultDomainError` → `vault_startup_error_result()` → `CommandResult(status="error")`; handler не вызывается | Проверить `ANKEY_VAULT_MASTER_KEYS` и доступность vault DB |
| Handler возвращает `None` | Трактуется как успех (`exit_code=0`); `_apply_cli_result_to_report()` — no-op | Нормально для команд без явного CommandResult (редко) |
| `report_dir` не существует | `writeReportJson()` создаёт через `makedirs(exist_ok=True)` | Без специальных действий |
| `finalizeReport()` до вызова handler | `context["runtime"]` перезаписан handler'ом (если handler тоже пишет в "runtime") | Не писать в "runtime" из handler; использовать другие ключи |

### ⚠️ Инварианты системы

1. **Инвариант: finalizeReport() перед writeReportJson()**
   - **Что**: `report.finish()` вызывается до `report.build()` в `writeReportJson()`.
   - **Почему важно**: Иначе `meta.finished_at` и `meta.duration_ms` будут `null` в JSON.
   - **Где проверяется**: `_finalize_report_artifacts()` всегда вызывает их в правильном порядке.

2. **Инвариант: Один ReportCollector на invocation**
   - **Что**: `createEmptyReport()` создаёт ровно один collector per `run_with_report()`.
   - **Почему важно**: Конкурентные procs не смешивают данные.
   - **Где проверяется**: `run_with_report()` — локальная переменная `report`, не глобальная.

3. **Инвариант: _shutdown_container_resources() всегда вызывается**
   - **Что**: DI-ресурсы корректно завершаются даже при ошибке handler.
   - **Почему важно**: Предотвращает утечки соединений к SQLite vault DB.
   - **Где проверяется**: try/finally в `run_with_report()`.

4. **Инвариант: exit code из CommandResult.status**
   - **Что**: OS exit code всегда и только из `_exit_code_from_result()`.
   - **Почему важно**: CI/CD pipeline полагается на exit code для определения успеха.
   - **Где проверяется**: `run_with_report()` возвращает `int`, который typer передаёт как `Exit(code=...)`.

### ⏱️ Performance заметки

**Узкие места**:
- `writeReportJson()` с `json.dump()` + `indent=2` при 1000 items: ~5–20 мс — незначительно.
- `_initialize_container_resources()` включает vault DB probe (write + read): ~50–200 мс при первом запуске.
- `inspect.signature()` в `_call_handler()`: ~1–5 мс — выполняется один раз на invocation.

**Оптимизации**:
- `asdict_report()` глубоко копирует только при `build()`; повторные вызовы без изменений collector — дополнительные копии.
- `makedirs(exist_ok=True)` в `writeReportJson()` — syscall, не блокирует при существующей директории.

---

## 🛠️ Как расширять

### Добавить новую команду с отчётом

1. Реализовать handler в 3-param стиле:
   ```python
   def handle_my_command(args: MyArgs, container: AppContainer, report: ReportCollector) -> CommandResult:
       report.set_meta(dataset=args.dataset, ...)
       # ... логика ...
       return CommandResult()
   ```

2. Зарегистрировать в CLI через `run_with_report()`:
   ```python
   @app.command("my-command")
   def my_command(args: MyArgs):
       container = build_container(args)
       exit_code = run_with_report("my_command", args, handle_my_command, container)
       raise typer.Exit(code=exit_code)
   ```

3. (Опционально) добавить маппинг в `_stage_for_command()`:
   ```python
   "my_command": DiagnosticStage.MY_STAGE,
   ```

### Мигрировать legacy 2-param handler на 3-param

```python
# До:
def handle_enrich(args: EnrichArgs, container: AppContainer) -> CommandResult:
    ...

# После:
def handle_enrich(args: EnrichArgs, container: AppContainer, report: ReportCollector) -> CommandResult:
    report.set_meta(dataset=args.dataset, app_version=APP_VERSION, git_rev=GIT_REV)
    # теперь stager processors могут использовать report
    ...
```

`_call_handler()` автоматически определит новый стиль по количеству параметров — никаких изменений в `run_with_report()` не нужно.

### Добавить новый контекстный блок из инфраструктуры

Если новый сервис должен записывать данные в `context`, реализовать по аналогии с `attach_dictionary_report_snapshot_if_available()`:
```python
def attach_my_service_context(*, ctx, report) -> None:
    if report is None:
        return
    service = getattr(getattr(ctx, "container", None), "my_service", None)
    if service is None:
        return
    data = service().snapshot()
    if isinstance(data, dict):
        report.set_context("my_service", data)
```

Вызвать в конце handler (или в runtime после handler).

---

## ❓ FAQ

### Почему ReportCollector не является DI-managed Singleton?

`ReportCollector` stateful и привязан к конкретному invocation — каждый запуск команды должен иметь свой изолированный collector. DI Singleton создаётся один раз на время жизни контейнера (обычно весь процесс) — это противоречит per-invocation семантике.

Factory-provider (`providers.Factory`) создавал бы новый экземпляр при каждом `()`, но тогда теряется возможность передать один экземпляр через все стадии конвейера. Явная передача через параметр — самое простое и понятное решение.

---

### Как тестировать command handler без реального DI?

```python
def test_handle_import_with_mock_report():
    from unittest.mock import MagicMock, create_autospec

    report = ReportCollector(run_id="test", command="import", started_at=datetime.now())
    container = MagicMock()
    args = ImportArgs(dataset="employees", source="data.csv", run_id="test")

    result = handle_import(args, container, report)

    assert result.status in ("ok", "warn", "error")
    # Проверить, что context заполнен
    report.finish()
    envelope = report.build()
    assert "input" in envelope.context
```

---

### Что если report_dir не задан (args.report_dir = None)?

`writeReportJson()` не вызывается — проверка в `_finalize_report_artifacts()`:
```python
report_dir = getattr(args, "report_dir", None)
if report_dir:
    writeReportJson(report, report_dir, file_base)
```

`finalizeReport()` при этом всё равно вызывается, `report.finish()` выполняется. Collector можно использовать для `report.build()` в тестах даже без записи на диск.

---

### Как убедиться что handler корректно определяется как 3-param?

`_call_handler()` использует `inspect.signature()` и считает параметры без `self`. Если handler — это метод класса, убедитесь что он декорирован `@staticmethod` или передаётся как bound method (тогда `self` уже привязан и не считается). Для standalone-функций — просто считаются все параметры:
- `def handle(args, container)` → 2 параметра → legacy режим
- `def handle(args, container, report)` → 3 параметра → report режим
- `def handle(args, container, report, extra)` → 4 параметра → также попадёт в report режим (>= 3)

---

### Зачем `_apply_cli_result_to_report()` создаёт `ReportItem` без `row_ref`?

CLI-level ошибки (vault startup failure, cache error) не привязаны к конкретной строке данных — они возникают до обработки строк. Хранение их как `ReportItem` с `row_ref=None` позволяет:
1. Включить ошибку в `summary.by_stage` (видна в JSON-отчёте).
2. Избежать отдельного поля для CLI-level errors (единая модель для всех ошибок).

Инструменты, читающие отчёт, должны обрабатывать `row_ref=null` — это нормальный вариант.

---

### Как run_with_report() обрабатывает исключение из handler?

Если handler бросает необработанное исключение (не возвращает `CommandResult`):
1. Исключение всплывает из `_call_handler()`.
2. `_finalize_report_artifacts()` НЕ вызывается (нет try/finally вокруг handler).
3. `_shutdown_container_resources()` вызывается в блоке `finally` — DI ресурсы освобождаются.
4. JSON-файл НЕ создаётся.
5. Исключение продолжает всплывать → typer перехватывает как ошибку → exit code 1.

**Рекомендация**: Не бросайте исключения из handler — возвращайте `CommandResult(status="error")`.

---

## 🧪 Тестирование

### Unit-тест createEmptyReport

```python
def test_create_empty_report():
    report = createEmptyReport(
        runId="run-001",
        command="import",
        configSources=["/etc/ankey/app.yaml"],
    )

    assert report is not None
    # context["config"] установлен
    report.finish()
    envelope = report.build()
    assert envelope.context["config"]["config_sources"] == ["/etc/ankey/app.yaml"]
    assert envelope.meta.run_id == "run-001"
    assert envelope.meta.command == "import"
```

### Unit-тест finalizeReport

```python
def test_finalize_report_stamps_runtime():
    report = createEmptyReport("run-002", "apply", [])

    finalizeReport(
        report=report,
        durationMs=1234,
        logFile="logs/run-002.log",
        cacheDir="cache/",
        reportDir="reports/",
    )

    envelope = report.build()
    assert envelope.meta.finished_at is not None
    assert envelope.meta.duration_ms == 1234
    assert envelope.context["runtime"]["duration_ms"] == 1234
    assert envelope.context["runtime"]["log_file"] == "logs/run-002.log"
```

### Integration-тест writeReportJson (с tmp_path)

```python
def test_write_report_json(tmp_path):
    report = createEmptyReport("run-003", "import", [])
    report.add_item(status="OK", row_ref=None, payload=None, errors=[], warnings=[], meta={}, store=True)
    finalizeReport(report, durationMs=500, logFile=None, cacheDir=None, reportDir=str(tmp_path))

    writeReportJson(report, str(tmp_path), "run-003")

    json_path = tmp_path / "run-003.json"
    assert json_path.exists()

    import json
    data = json.loads(json_path.read_text())
    assert data["status"] == "SUCCESS"
    assert data["summary"]["rows_total"] == 1
    assert "config" in data["context"]
    assert "runtime" in data["context"]
```

### Unit-тест _call_handler dispatch

```python
def test_call_handler_3_param():
    calls = []

    def handler_3(args, container, report):
        calls.append(("3-param", report is not None))
        return CommandResult()

    report = ReportCollector(run_id="test", command="test", started_at=datetime.now())
    _call_handler(handler_3, "args", "container", report)
    assert calls == [("3-param", True)]


def test_call_handler_2_param():
    calls = []

    def handler_2(args, container):
        calls.append("2-param")
        return CommandResult()

    report = ReportCollector(run_id="test", command="test", started_at=datetime.now())
    _call_handler(handler_2, "args", "container", report)
    assert calls == ["2-param"]


def test_exit_code_from_result():
    assert _exit_code_from_result(None) == 0

    ok = CommandResult()
    ok.add_code(SystemErrorCode.OK)
    assert _exit_code_from_result(ok) == 0

    err = CommandResult()
    err.add_code(SystemErrorCode.DATA_INVALID)
    assert _exit_code_from_result(err) == 1
```

---

## 🔗 Связанные документы

- [report-models.md](./report-models.md) — ReportCollector, ReportEnvelope, все domain models
- [report-pipeline.md](./report-pipeline.md) — стадии конвейера как производители данных для отчёта
- [vault-delivery.md](../vault/vault-delivery.md) — VaultStartupGuard и vault_ready Resource в DI
- [dictionary-delivery.md](../dictionary/dictionary-delivery.md) — DictionaryContainer и telemetry

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Report Delivery| xORex-LC |
