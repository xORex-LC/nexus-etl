# Observability Logging (structlog Runtime & Sinks)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма потока лог-записи](#диаграмма-потока-лог-записи)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🎯 Redaction surface](#-redaction-surface)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
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

**Назначение**: Прод-модель логирования на **structlog** — единый processor-конвейер с корреляционным
контекстом, redaction и двумя sink'ами (файловый daily+size и консольный stderr).

**Ключевая ответственность**: Сконфигурировать один structlog-runtime на процесс, выдать
component-aware logger и развести вывод по каналам (stdout = результат, stderr = лог).

**Расположение в кодовой базе**:
- `connector/infra/logging/runtime.py` — structlog runtime, sinks, handler stack, renderers
- `connector/infra/logging/redaction.py` — `LogRedactionEngine`
- `connector/delivery/cli/stream_capture.py` — перехват stdout/stderr (`TeeStream`, `StdStreamToLogger`)
- `connector/common/interactive_io.py` — `InteractiveIoGate` (подавление вывода в интерактиве)

Реализует [OBSERVABILITY-DEC-001](../../../adr/observability/OBSERVABILITY-DEC-001-structlog-as-standard.md)
(structlog как стандарт). Stage Z завершил **native-миграцию**: legacy `setup.py`
(`create_command_logger`/`log_event`) и адаптер `LegacyCompatibleStructlogLogger` **удалены** — весь
код логирует через structlog напрямую.

> **Формат лог-строки (ECS)** — отдельная тема: миграция формата на Elastic Common Schema описана в
> [ecs-logging-conventions.md](./ecs-logging-conventions.md) и
> [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md).
> Этот документ описывает **runtime/sinks/transport**, а не ECS-поля.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
infra/logging/
├── runtime.py
│   ├── build_structured_logging_runtime()  # configure structlog + handler stack (once/process)
│   ├── StructuredLoggingRuntime            # фасад: get_logger / current_log_file_path / close
│   ├── StructlogHandlerStack               # console + file handlers на root logger
│   ├── DailySizeRotatingFileHandler        # daily + size файловый sink (thread RLock + fcntl-lock)
│   ├── LoggingRuntimeMeta                  # host/pid/app_version/git_rev в каждую запись
│   ├── _JsonTextRenderer                   # logfmt-подобный текст для файлового sink
│   ├── _HumanConsoleRenderer               # человекочитаемый console-вывод (с цветом на tty)
│   ├── _InteractiveConsoleSuppressFilter   # глушит console mirror во время prompt
│   ├── _build_structlog_processors()       # processor-цепочка
│   ├── _build_formatter()                  # ProcessorFormatter (foreign_pre_chain + redaction + renderer)
│   ├── bind_observability_context()        # bind_contextvars(run_id/pipeline_run_id/component/dataset)
│   └── clear_observability_context()
└── redaction.py
    └── LogRedactionEngine                  # key + regex redaction, structlog processor

delivery/cli/stream_capture.py
├── StdStreamToLogger                       # перехват построчно + redaction + interactive-suppress
└── TeeStream                               # дублирование в оригинальный stream + logger
```

> Legacy-фабрика `setup.py` и `LegacyCompatibleStructlogLogger`/`DropCapturedStdStreamsFilter`
> **удалены в Stage Z** — в актуальном коде их нет.

### 🎭 Применённые паттерны

#### Паттерн 1: structlog → stdlib bridge (ProcessorFormatter)

**Где применяется**: per-logger processor-цепочка заканчивается `ProcessorFormatter.wrap_for_formatter`;
фактический рендеринг и redaction — в `ProcessorFormatter` на handler'е. Foreign-логи (httpx/sqlite3)
проходят через `foreign_pre_chain` и получают то же обогащение.

**Реализация в коде**: `_build_structlog_processors()`, `_build_formatter()` в `runtime.py`.

**Зачем**: единый формат для structlog- и stdlib-логов; файловая ротация — обычный stdlib-handler.

#### Паттерн 2: Context Binding (contextvars)

**Где применяется**: `bind_observability_context()` один раз в начале команды биндит
`run_id/pipeline_run_id/component/dataset`; `merge_contextvars` добавляет их в каждую запись.

**Зачем**: корреляция без ручной передачи полей в каждый вызов.

#### Паттерн 3: Renderer Strategy (per-sink)

**Где применяется**: рендерер выбирается на каждый sink по конфигу формата:
- console: `JSONRenderer(ensure_ascii=False)` при `console.format == "json"`, иначе
  `_HumanConsoleRenderer(use_color=isatty)`;
- file: `JSONRenderer` при `file.format == "json"`, иначе `_JsonTextRenderer` (logfmt-подобный).

**Зачем**: один и тот же event_dict рендерится по-разному для машины (JSON/ELK) и человека (консоль).

### Диаграмма потока лог-записи

```
log.info("event", stage=..., dataset=...)            print("...")  → sys.stdout (TeeStream)
        │                                                    │
        ▼                                                    ▼ primary
  structlog processors                            original_stdout (человек)   + secondary
  (merge_contextvars[run_id,pipeline_run_id,                                    StdStreamToLogger
   component], add_log_level, TimeStamper(iso,utc),                            .write → redact → logger
   schema_version, runtime_meta[host/pid/app_version/git_rev],                       │ (если не interactive)
   wrap_for_formatter)                                                               ▼
        │                                                              (та же processor-цепочка)
        ▼
  ProcessorFormatter (на handler'ах):
   foreign_pre_chain → ExceptionRenderer → redaction → remove_processors_meta → renderer
        ├──────────────▶ console handler (+ interactive-suppress filter) → stderr
        │                    renderer = JSONRenderer | _HumanConsoleRenderer
        └──────────────▶ DailySizeRotatingFileHandler → var/logs/<component>/<date>_<component>.log
                             renderer = JSONRenderer | _JsonTextRenderer
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `StructuredLoggingRuntime` | Фасад runtime для одного компонента | `get_logger()`, `current_log_file_path()`, `close()` |
| `StructlogHandlerStack` | console+file handlers на root | `close()` (removeHandler + close) |
| `DailySizeRotatingFileHandler` | Файловый sink daily+size | `emit()`, `current_path` |
| `_HumanConsoleRenderer` / `_JsonTextRenderer` | Рендереры консоли/файла (не-JSON) | `__call__` |
| `_InteractiveConsoleSuppressFilter` | Глушит console mirror в prompt-режиме | `filter()` |
| `LogRedactionEngine` | Маскирование секретов | `processor()`, `redact_value()`, `redact_text()` |
| `StdStreamToLogger` / `TeeStream` | Перехват stdout/stderr | `write()`, `flush()` |

### Свободные функции

| Функция | Назначение |
|---------|------------|
| `build_structured_logging_runtime()` | configure structlog + собрать handler stack (вызывается DI Resource) |
| `bind_observability_context()` / `clear_observability_context()` | bind/clear contextvars |

> **Нет** `IReportRenderer`-подобной абстракции у логгера: `get_logger()` возвращает напрямую
> `structlog.stdlib.BoundLogger` (с `bind(component=...)`). Legacy-адаптер удалён.

---

## 🗂️ Модели данных

### Dataclass: `LoggingRuntimeMeta`

```python
@dataclass(frozen=True)
class LoggingRuntimeMeta:
    app_version: str | None = None
    git_rev: str | None = None
```

**Назначение**: статические поля runtime, добавляемые processor'ом `_build_runtime_meta_processor`
вместе с `host`/`pid`. `schema_version` лог-строки — константа `_LOG_SCHEMA_VERSION` (`"1.0"`).

### Dataclass: `StructlogHandlerStack`

```python
@dataclass(frozen=True)
class StructlogHandlerStack:
    console_handler: logging.Handler | None
    file_handler: DailySizeRotatingFileHandler | None
    root_logger: logging.Logger
```

**Lifecycle**: создаётся в `build_structured_logging_runtime`; `close()` снимает handlers с root и
закрывает их (вызывается из `StructuredLoggingRuntime.close()` → DI Resource teardown).

---

## 🎯 Redaction surface

`LogRedactionEngine` — единый движок (политика из `ObservabilityRedactionPolicy`, ключи —
`DEFAULT_SENSITIVE_FIELD_KEYS`). Маскирует в **четырёх** местах общей processor-цепочки + одном на
перехвате:

| Поверхность | Что | Как |
|-------------|-----|-----|
| structlog `event_dict` (kwargs) | `log.info("e", token=...)` | по **ключу** (`redact_value`) |
| строковые значения, включая `event` | `log.info("password=...")` | по **regex** (`redact_text`) |
| исключения/traceback | `logger.exception(...)` | `ExceptionRenderer` → затем `redaction.processor` |
| foreign/stdlib-логи | httpx/sqlite3 | тот же processor через `foreign_pre_chain` |
| перехват stdout/stderr | `print()`/трейсы | `StdStreamToLogger._redact()` **перед** эмиссией |

> Redaction — defense-in-depth, не замена дисциплине «не логировать секреты». Значения payload в
> отчётах маскирует отдельный `PayloadSanitizer` (см. [report layer](../report/report-models.md)),
> но **тем же** набором ключей (`DEFAULT_SENSITIVE_FIELD_KEYS`).

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `DailySizeRotatingFileHandler.emit()` | O(1) на запись | append + daily-switch + size-roll под thread+process локом |

### Метод: `DailySizeRotatingFileHandler.emit()`

**Расположение**: `connector/infra/logging/runtime.py`

**Назначение**: записать строку в дневной файл компонента, переключаясь на новый файл при смене дня и
ролля по размеру внутри дня; потокобезопасно (thread `RLock`) **и** межпроцессно (`fcntl.flock` на
файле `<name>.lock`).

**Алгоритм**:
```
1. message = self.format(record)
2. with self._lock (RLock):
   a. active_path = layout.log_file(component, now=clock())   # имя зависит от текущей даты
   b. with self._acquire_process_lock(active_path):           # fcntl.LOCK_EX на <name>.lock
        _ensure_stream(active_path):
          IF current_path != active_path → закрыть старый stream, открыть active_path "a"  (DAILY switch)
        _maybe_roll_by_size(active_path, message):
          IF (current_size>0) AND (current_size + len(line) > max_bytes):
            закрыть stream → _rotate_size() (.N→.N+1, active→.1) → переоткрыть
        write(message + "\n"); flush()
3. except: handleError(record)   # ошибка sink не ломает приложение
```

**Инварианты**:
1. Активный файл всегда `<date>_<component>.log`; size-роллы — `<date>_<component>.<n>.log`.
2. Операции открытия/ротации сериализованы thread-локом **и** межпроцессным `fcntl`-локом
   (несколько процессов в общий каталог компонента не повреждают файл/ротацию).
3. Исключение в `emit` не пробрасывается наружу (`handleError`).

**Edge cases**: пустой файл (`current_size==0`) — без size-roll; смена дня — новый файл создаётся
лениво при первом `emit` нового дня.

**Связанные методы**: `_ensure_stream()`, `_maybe_roll_by_size()`, `_rotate_size()`,
`_acquire_process_lock()`, `ObservabilityLayout.log_file()`.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| common/observability | Зависимость | `ObservabilityLayout`, `ObservabilityRedactionPolicy`, `ServiceComponent` | пути лог-файлов, ключи redaction |
| common/interactive_io | Зависимость | `InteractiveIoGate` | подавление вывода во время prompt |
| config | Зависимость | `LoggingConfig` | level/components/sinks/redaction |
| delivery/cli/runtime | Потребитель/wiring | `build_structured_logging_runtime`, `bind/clear_observability_context` | DI Resource + контекст команды |
| delivery/cli/stream_capture | Использует | `LogRedactionEngine`, `InteractiveIoGate` | redaction/suppress перехвата |
| report layer | Косвенно | общий `DEFAULT_SENSITIVE_FIELD_KEYS` | согласованный набор секретных ключей |

---

## 🔌 Контракты и границы

### Runtime-контракт

`build_structured_logging_runtime(*, config, layout, redaction_engine, component, stderr_stream=None,
root_logger_name="", clock=None, app_version=None, git_rev=None, interactive_io_gate=None)` →
`StructuredLoggingRuntime`:
- конфигурирует **root** logger (console → `stderr_stream`/resolved stream, file →
  `DailySizeRotatingFileHandler`) и глобальный structlog **один раз на процесс**;
- `get_logger(component, *, logger_name=None)` → `structlog.stdlib.BoundLogger`
  (logger `nexus.<component>`, `bind(component=...)`, propagate → root);
- `current_log_file_path()` → активный путь файла либо ожидаемый путь текущего дня;
- `close()` снимает handlers и чистит contextvars (вызывается DI Resource teardown).

**Гарантии**:
- console-sink пишет в **stderr** по умолчанию (`ConsoleLoggingSinkConfig.stream`, default `stderr`);
  при `stderr_stream` он используется напрямую (так оркестратор передаёт «оригинальный» stderr).
- per-component уровень: `LoggingConfig.components[<c>].level` переопределяет `level`
  (`_level_for_component` → `_coerce_log_level`).

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `infra/logging` → `common/observability`, `common/interactive_io`, `config/models` (`LoggingConfig`),
  `structlog`, stdlib
- ✅ `delivery/cli/stream_capture` → `infra/logging/redaction`, `common/interactive_io`

**Запрещённые**:
- ❌ `infra/logging` → `usecases/`, `delivery/`
- ❌ structlog вне whitelisted путей (`tests/architecture/test_target_layer_boundaries.py`:
  `ALLOWED_STRUCTLOG_IMPORT_PATHS` включает `infra/logging/runtime.py`)

---

## 💡 Типичные сценарии

### Сценарий 1: логирование в команде

```python
log = runtime.get_logger(ServiceComponent.ENRICHER)
log.info("row_processed", row_id=row_id, status="ok")   # run_id/pipeline_run_id/component добавятся сами
```

### Сценарий 2: перехваченный stdout

```python
print("hello")   # → реальный stdout (TeeStream.primary) И → StdStreamToLogger → log (captured_stream="stdout")
```
В интерактивном prompt-режиме (`InteractiveIoGate.is_active()`) перехват глушится (`_capture_suppressed`),
а console-sink — фильтром `_InteractiveConsoleSuppressFilter`.

---

## 📌 Важные детали

### Особенности реализации

- **`current_log_file_path()`** возвращает активный путь handler'а либо ожидаемый путь текущего дня
  (используется для `RUNTIME` report-контекста и ledger).
- **Межпроцессный лок** (`fcntl.flock` на `<name>.lock`) — поверх thread-лока, для общих каталогов
  компонента из нескольких процессов.
- **Stage Z**: legacy `setup.py`/`LegacyCompatibleStructlogLogger`/`DropCapturedStdStreamsFilter`
  удалены; добавлены `_HumanConsoleRenderer`, `_JsonTextRenderer`, `_InteractiveConsoleSuppressFilter`,
  `InteractiveIoGate` (подавление в интерактиве).

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| Любая ошибка в `emit()` | сбой записи в файл | `handleError(record)` — не пробрасывается | проверить права/диск на `log_dir` |
| Рекурсия через `logging.lastResort` (исторический) | при teardown root остаётся без handlers, а `sys.stderr` ещё `TeeStream` | **устранено**: stdout/stderr восстанавливаются до shutdown (см. [runtime](./observability-runtime.md)) | — |

### ⚠️ Инварианты системы

1. **Инвариант: dual transport**
   - **Что**: stdout = результат/presenter, stderr = лог. Лог **не** идёт в stdout.
   - **Почему важно**: `nexus ... > out` остаётся валидным; journald/ELK ловят оба потока.
   - **Где проверяется**: `ConsoleLoggingSinkConfig.stream` (default `stderr`); оркестратор передаёт
     `stderr_stream`; e2e на чистоту stdout.
2. **Инвариант: один runtime на процесс**
   - **Что**: `build_structured_logging_runtime` конфигурирует root+structlog один раз.
   - **Почему важно**: готовит per-service модель; избегает дублей handlers.
3. **Инвариант: thread- и process-safe файловый sink**
   - **Что**: `emit/rotate` под `RLock` + `fcntl.flock`.
   - **Почему важно**: конкурентный `import apply` / несколько процессов не повреждают файл/ротацию.

### ⏱️ Performance заметки

- `emit()` делает `stat()` активного файла на каждую запись для size-guard и берёт `fcntl`-лок —
  приемлемо при daily+size с большим `max_bytes`; узким местом не является.

### Частые ошибки

- ❌ Слать лог в stdout.
- ✅ console-sink → stderr; человекочитаемый результат печатает presenter в stdout.

---

## 🛠️ Как расширять

### Добавить новый формат/рендерер sink'а
1. Реализовать renderer-callable (как `_JsonTextRenderer`/`_HumanConsoleRenderer`).
2. Выбрать его в `_build_handler_stack` по соответствующему `*.format` из `LoggingConfig`.

### Добавить поле во все записи
1. Добавить processor в `_build_structlog_processors` (или расширить `_build_runtime_meta_processor`).
2. Для foreign-логов оно появится автоматически (`foreign_pre_chain` = `processors[:-1]`).

---

## 🔗 Связанные документы

- [Observability Model](./observability-model.md) — layout (пути лог-файлов), redaction policy
- [Observability Config](./observability-config.md) — `logging.*` секция
- [Observability Runtime](./observability-runtime.md) — wiring, bind/clear, restore-streams инвариант
- [ECS Logging Conventions](./ecs-logging-conventions.md) — формат лог-строки (ECS-поля)
- ADR: `OBSERVABILITY-DEC-001` (structlog), `OBSERVABILITY-DEC-003` (ECS renderer/field-mapping)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002 Stage 2) | xorex-LC |
| 2026-06 | Сверка с кодом: убраны `setup.py`/`LegacyCompatibleStructlogLogger`/`DropCapturedStdStreamsFilter`; `get_logger`, `_coerce_log_level`, Stage-Z renderers, fcntl-lock, interactive-suppress | xorex-LC |
