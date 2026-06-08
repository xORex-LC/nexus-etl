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
контекстом, redaction и двумя sink'ами (файловый daily+size и структурный stderr).

**Ключевая ответственность**: Сконфигурировать один structlog-runtime на процесс, выдать
component-aware логгер и legacy-совместимый адаптер, и развести вывод по каналам (stdout = результат,
stderr = структурный лог).

**Расположение в кодовой базе**:
- `connector/infra/logging/runtime.py` — structlog runtime, sinks, handler stack, legacy-адаптер
- `connector/infra/logging/redaction.py` — `LogRedactionEngine`
- `connector/infra/logging/setup.py` — legacy-фасад (`create_command_logger`, `log_event`) на время switch-over
- `connector/delivery/cli/stream_capture.py` — перехват stdout/stderr (`TeeStream`, `StdStreamToLogger`)

Реализует [OBSERVABILITY-DEC-001](../../../adr/observability/OBSERVABILITY-DEC-001-structlog-as-standard.md)
(structlog как стандарт): файловая ротация остаётся stdlib-handler'ом **под** structlog через
`ProcessorFormatter` bridge.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
infra/logging/
├── runtime.py
│   ├── build_structured_logging_runtime()  # configure structlog + handler stack (once/process)
│   ├── StructuredLoggingRuntime            # фасад: get_command_logger / current_log_file_path / close
│   ├── StructlogHandlerStack               # console + file handlers на root logger
│   ├── DailySizeRotatingFileHandler        # daily + size файловый sink
│   ├── LegacyCompatibleStructlogLogger     # мост для log_event(..., extra=...)
│   ├── LoggingRuntimeMeta                  # app_version/git_rev в каждую запись
│   ├── _build_structlog_processors()       # processor-цепочка
│   ├── _build_formatter()                  # ProcessorFormatter (foreign_pre_chain + redaction + renderer)
│   ├── bind_observability_context()        # bind_contextvars(run_id/pipeline_run_id/component/dataset)
│   └── clear_observability_context()
├── redaction.py
│   └── LogRedactionEngine                  # key + regex redaction, structlog processor
└── setup.py                                # legacy facade (выводится из употребления — Этап Z)

delivery/cli/stream_capture.py
├── StdStreamToLogger                       # перехват построчно + redaction
├── TeeStream                               # дублирование в оригинальный stream + logger
└── DropCapturedStdStreamsFilter            # анти-задвоение console-mirror
```

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

**Зачем**: корреляция без ручной передачи полей в каждый вызов (закрывает `EnsureFieldsFilter`-workaround
из [PROBLEM-001](../../../adr/observability/OBSERVABILITY-PROBLEM-001-inconsistent-logging.md)).

#### Паттерн 3: Adapter (legacy compatibility)

**Где применяется**: `LegacyCompatibleStructlogLogger` адаптирует structlog BoundLogger к
stdlib-подобному API (`log/info/warning/error/exception`, `extra={runId,component}`), которым ещё
пользуются legacy call-sites через `log_event(...)`.

**Зачем**: switch-over без правки каждого call-site; `extra` мапится в `run_id`/`scope`/`captured_stream`.

### Диаграмма потока лог-записи

```
log.info("event", stage=..., dataset=...)            print("...")  → sys.stdout (TeeStream)
        │                                                    │
        ▼                                                    ▼ primary
  structlog processors                            original_stdout (человек)   + secondary
  (merge_contextvars[run_id,pipeline_run_id,                                    StdStreamToLogger
   component], add_log_level, TimeStamper(utc),                                 .write → redact → logger
   schema_version, runtime_meta, wrap_for_formatter)                                  │
        │                                                                             ▼
        ▼                                                              (попадает в ту же цепочку)
  ProcessorFormatter (на handler'ах):
   foreign_pre_chain → ExceptionRenderer → redaction → renderer
        ├──────────────▶ console handler  → JSONRenderer → stderr   (journald/ELK)
        └──────────────▶ DailySizeRotatingFileHandler → var/logs/<component>/<date>_<component>.log
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `StructuredLoggingRuntime` | Фасад runtime для одного компонента | `get_command_logger()`, `current_log_file_path()`, `close()` |
| `StructlogHandlerStack` | console+file handlers на root | `close()` (removeHandler + close) |
| `DailySizeRotatingFileHandler` | Файловый sink daily+size | `emit()`, `current_path` |
| `LegacyCompatibleStructlogLogger` | Мост к legacy API | `log()`, `info/warning/error/exception()`, `isEnabledFor()` |
| `LogRedactionEngine` | Маскирование секретов | `processor()`, `redact_value()`, `redact_text()` |
| `StdStreamToLogger` / `TeeStream` | Перехват stdout/stderr | `write()`, `flush()` |

### Свободные функции

| Функция | Назначение |
|---------|------------|
| `build_structured_logging_runtime()` | configure structlog + собрать handler stack (вызывается DI Resource) |
| `bind_observability_context()` / `clear_observability_context()` | bind/clear contextvars |

---

## 🗂️ Модели данных

### Dataclass: `LoggingRuntimeMeta`

```python
@dataclass(frozen=True)
class LoggingRuntimeMeta:
    app_version: str | None = None
    git_rev: str | None = None
```

**Назначение**: статические поля runtime, добавляемые в каждую запись processor'ом `_add_runtime_meta`
(вместе с `host`/`pid`). `schema_version` лог-строки — константа `_LOG_SCHEMA_VERSION` (`"1.0"`).

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
`DEFAULT_SENSITIVE_FIELD_KEYS`). Маскирует в **пяти точках**, чтобы «единый источник ключей» давал
единое поведение:

| Поверхность | Что | Как |
|-------------|-----|-----|
| structlog `event_dict` (kwargs) | `log.info("e", token=...)` | по **ключу** |
| строковые значения, включая `event` | `log.info("password=...")` | по **regex** |
| исключения/traceback | `logger.exception(...)` | `ExceptionRenderer` → redaction по regex |
| foreign/stdlib-логи | httpx/sqlite3 | тот же processor через `foreign_pre_chain` |
| перехват stdout/stderr | `print()`/трейсы | `StdStreamToLogger._redact()` **перед** эмиссией |

> Redaction — defense-in-depth, не замена дисциплине «не логировать секреты». Значения payload в
> отчётах маскирует отдельный `PayloadSanitizer` (см. [report layer](../report/report-models.md)),
> но **тем же** набором ключей.

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `DailySizeRotatingFileHandler.emit()` | O(1) на запись | append + daily-switch + size-roll под локом |

### Метод: `DailySizeRotatingFileHandler.emit()`

**Расположение**: `connector/infra/logging/runtime.py`

**Назначение**: записать строку в дневной файл компонента, переключаясь на новый файл при смене дня и
ролля по размеру внутри дня; всё — потокобезопасно (под `RLock`).

**Алгоритм**:
```
1. message = self.format(record)
2. with self._lock:
   a. active_path = layout.log_file(component, now=clock())   # имя зависит от текущей даты
   b. _ensure_stream(active_path):
        IF current_path != active_path → закрыть старый stream, открыть active_path в режиме "a"
        (это и есть DAILY-переключение: имя меняется при смене дня)
   c. _maybe_roll_by_size(active_path, message):
        IF (current_size>0) AND (current_size + len(line) > max_bytes):
          закрыть stream → _rotate_size() → переоткрыть
        _rotate_size(): сдвиг бэкапов .N→.N+1, active→.1, очистка overflow
   d. write(message + "\n"); flush()
3. except: handleError(record)   # ошибка sink не ломает приложение
```

**Временная сложность**: O(1) на запись (плюс редкий O(backup_count) сдвиг при size-roll).

**Инварианты**:
1. Активный файл всегда `<date>_<component>.log`; size-роллы — `<date>_<component>.<n>.log`.
2. Все операции открытия/ротации сериализованы локом (безопасно под конкурентным `import apply`).
3. Исключение в `emit` не пробрасывается наружу (`handleError`).

**Edge cases**:
- Пустой активный файл (`current_size==0`) — size-roll не выполняется.
- Смена дня — новый файл создаётся лениво при первом `emit` нового дня.

**Связанные методы**: `_ensure_stream()`, `_maybe_roll_by_size()`, `_rotate_size()`,
`ObservabilityLayout.log_file()` (имя).

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| common/observability | Зависимость | `ObservabilityLayout`, `ObservabilityRedactionPolicy`, `ServiceComponent` | пути лог-файлов, ключи redaction |
| config | Зависимость | `LoggingConfig` | level/components/sinks/redaction |
| delivery/cli/runtime | Потребитель/wiring | `build_structured_logging_runtime`, `bind/clear_observability_context` | DI Resource + контекст команды |
| delivery/cli/stream_capture | Использует | `LogRedactionEngine` | redaction перехваченных строк |
| report layer | Косвенно | общий `DEFAULT_SENSITIVE_FIELD_KEYS` | согласованный набор секретных ключей |

---

## 🔌 Контракты и границы

### Runtime-контракт

`build_structured_logging_runtime(config, layout, redaction_engine, component, stderr_stream,
root_logger_name="")` → `StructuredLoggingRuntime`:
- конфигурирует **root** logger (console → `stderr_stream`, file → `DailySizeRotatingFileHandler`) и
  глобальный structlog **один раз на процесс**;
- `get_command_logger(command_name, component)` → `LegacyCompatibleStructlogLogger`
  (логгер `nexus.<component>.<command>`, propagate → root);
- `close()` снимает handlers и чистит contextvars (вызывается DI Resource teardown).

**Гарантии**:
- console-sink пишет JSON в **stderr** (не stdout) — `stream` берётся из `ConsoleLoggingSinkConfig`
  (default `stderr`).
- per-component уровень: `LoggingConfig.components[<c>].level` переопределяет `level`.

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `infra/logging` → `common/observability`, `config/models` (`LoggingConfig`), `structlog`, stdlib
- ✅ `delivery/cli/stream_capture` → `infra/logging/redaction`, `infra/logging/setup`

**Запрещённые**:
- ❌ `infra/logging` → `usecases/`, `delivery/`
- ❌ structlog вне whitelisted путей (контролируется `tests/architecture/test_target_layer_boundaries.py`:
  `ALLOWED_STRUCTLOG_IMPORT_PATHS` включает `infra/logging/runtime.py`)

---

## 💡 Типичные сценарии

### Сценарий 1: логирование в команде (новый код)

```python
log = runtime.get_command_logger(command_name="enrich", component=ServiceComponent.ENRICHER)
log.info("row_processed", row_id=row_id, status="ok")   # run_id/pipeline_run_id/component добавятся сами
```

### Сценарий 2: legacy call-site

```python
log_event(logger, logging.INFO, run_id, "cache", "refresh done")  # адаптер мапит extra → структурные поля
```

---

## 📌 Важные детали

### Особенности реализации

- **`current_log_file_path()`** возвращает активный путь handler'а либо ожидаемый путь текущего дня
  (для `RUNTIME` report-контекста и ledger).
- **`setup.py` — legacy-фасад**: `create_command_logger`/`EnsureFieldsFilter`/`map_log_level`
  выводятся из употребления и удаляются на Этапе Z (по DEC-001).

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| Любая ошибка в `emit()` | сбой записи в файл | `handleError(record)` — не пробрасывается | проверить права/диск на `log_dir` |
| Рекурсия через `logging.lastResort` (исторический баг) | при teardown root остаётся без handlers, а `sys.stderr` ещё `TeeStream` | **устранено**: stdout/stderr восстанавливаются до shutdown (см. [runtime](./observability-runtime.md)) | — |

### ⚠️ Инварианты системы

1. **Инвариант: dual transport**
   - **Что**: stdout = результат/presenter, stderr = структурный JSON-лог. Структурный лог **никогда**
     не идёт в stdout.
   - **Почему важно**: `nexus ... > out` остаётся валидным; journald/ELK ловят оба потока.
   - **Где проверяется**: `ConsoleLoggingSinkConfig.stream` (default `stderr`); e2e на чистоту stdout.
2. **Инвариант: один runtime на процесс**
   - **Что**: `build_structured_logging_runtime` конфигурирует root+structlog один раз.
   - **Почему важно**: готовит per-service модель; избегает дублей handlers.
3. **Инвариант: thread-safe файловый sink**
   - **Что**: `emit/rotate` под `RLock`.
   - **Почему важно**: конкурентный `import apply` не повреждает файл/ротацию.

### ⏱️ Performance заметки

- `emit()` делает `stat()` активного файла на каждую запись для size-guard — приемлемо при daily+size
  с большим `max_bytes`; узким местом не является.

### Частые ошибки

- ❌ Слать структурный лог в stdout.
- ✅ console-sink → stderr; человекочитаемый результат печатает presenter в stdout.

---

## 🔗 Связанные документы

- [Observability Model](./observability-model.md) — layout (пути лог-файлов), redaction policy
- [Observability Config](./observability-config.md) — `logging.*` секция
- [Observability Runtime](./observability-runtime.md) — wiring, bind/clear, restore-streams инвариант
- ADR: `OBSERVABILITY-DEC-001` (structlog), `OBSERVABILITY-DEC-002` (per-component модель)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002 Stage 2, DEC-001 structlog) | — |
