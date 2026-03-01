# CLI/Settings Layer

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [Особенности реализации](#особенности-реализации)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
  - [Частые ошибки](#частые-ошибки)
  - [Что нужно помнить](#что-нужно-помнить)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: слой объединяет загрузку конфигурации и runtime-исполнение CLI-команд так, чтобы команды/use-cases получали только профильные settings-slices, а не полную модель настроек.

**Ключевая ответственность**:
1. Загрузить настройки из `CLI > ENV > config > defaults`.
2. Провалидировать значения и инварианты.
3. Сформировать `AppSettings` (slices-модель) и `CommandContext`.
4. Запустить команду через единый lifecycle (`run_with_report` / `run_without_report`).
5. Преобразовать settings-ошибки в `DiagnosticItem`.

**Расположение в кодовой базе**:
1. `connector/config/config.py`
2. `connector/config/app_settings.py`
3. `connector/config/diagnostics.py`
4. `connector/delivery/cli/app.py`
5. `connector/delivery/cli/context.py`
6. `connector/delivery/cli/requirements.py`
7. `connector/delivery/cli/runtime.py`
8. `connector/delivery/cli/settings_slice_map.py`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/config/
├── config.py                # Flat Settings, merge chain, parse/validate, typed errors
├── app_settings.py          # Slices + AppSettings + mapping
├── diagnostics.py           # SettingsIssue -> DiagnosticItem adapter
└── __init__.py              # Public config API

connector/delivery/cli/
├── app.py                   # Composition root (main callback)
├── context.py               # CommandContext + CommandPaths
├── requirements.py          # Requirements contract
├── runtime.py               # run_with_report / run_without_report
├── settings_slice_map.py    # Command/use-case -> slices contract map
└── bootstrap.py             # Wiring factories (cache/api/pipeline)
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Settings Class](../../../uml/config/settings_class.png) | `Settings`, `AppSettings`, slices, typed errors |
| Component | [Settings Component](../../../uml/config/settings_component.png) | Поток config + runtime компонентов |
| Sequence | [Settings Load Sequence](../../../uml/config/settings_sequence_load.png) | Загрузка настроек и error path |
| Boundary | [Settings Boundary](../../../uml/config/settings_boundary.png) | Архитектурные границы по доступу к settings |
| Class | [CLI Layer Class](../../../uml/pipeline/cli_layer/cli_layer_class.png) | Классы CLI orchestration |
| Component | [CLI Layer Components](../../../uml/pipeline/cli_layer/cli_layer_components.png) | Компоненты CLI-слоя |
| Sequence | [CLI Layer Sequence](../../../uml/pipeline/cli_layer/cli_layer_sequence.png) | Взаимодействие команд/слоёв |
| Activity | [CLI Layer Activity](../../../uml/pipeline/cli_layer/cli_layer_activity.png) | Общий сценарий выполнения команды |

**PlantUML исходники**:
1. `docs/uml/config/*.puml`
2. `docs/uml/pipeline/cli_layer/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Composition Root

**Где применяется**: `connector/delivery/cli/app.py` (`main`, `_build_ctx`).

**Реализация в коде**:
- **Root**: `main(...)` line 78 собирает CLI-overrides, вызывает `load_app_settings`, заполняет `ctx.obj`.
- **Context Builder**: `_build_ctx(...)` line 47 формирует `CommandContext`.

**Пример использования**:
```python
loaded_app = load_app_settings(config_path=config, cli_overrides=cliOverrides)
ctx.obj = {
    "runId": runId,
    "app_settings": loaded_app.app_settings,
    "sources": list(loaded_app.sources_used),
}
```

**Зачем**: единая входная точка для full settings-модели и строгий контроль границ вниз по стеку.

#### Паттерн 2: Adapter

**Где применяется**: `connector/config/diagnostics.py`.

**Реализация в коде**:
- **Source**: `SettingsIssue`, `SettingsLoadError`.
- **Adapter Functions**: `translate_settings_issue`, `translate_settings_load_error`, `translate_settings_warnings`.
- **Target**: `DiagnosticItem`.

**Пример использования**:
```python
diags = translate_settings_load_error(
    catalog=catalog,
    stage=DiagnosticStage.SINK,
    error=exc,
)
```

**Зачем**: единый диагностический контракт без смешивания config-логики с runtime/reporting деталями.

#### Паттерн 3: Contract Map

**Где применяется**: `connector/delivery/cli/settings_slice_map.py`.

**Реализация в коде**:
- `COMMAND_SETTINGS_SLICE_MAP`
- `USECASE_SETTINGS_SLICE_MAP`
- `COMMAND_TO_USECASE`

**Пример использования**:
```python
extra["settings_contract"] = {
    "command_slices": [t.__name__ for t in COMMAND_SETTINGS_SLICE_MAP.get(command_key, ())],
}
```

**Зачем**: формализует и документирует, какие настройки доступны конкретной команде/use-case.

#### Паттерн 4: Template Method

**Где применяется**: `connector/delivery/cli/runtime.py` (`run_with_report`).

**Реализация в коде**:
- каркас lifecycle в `run_with_report(...)` line 47;
- handler передаётся как параметр, а runtime-обвязка одна.

**Пример использования**:
```python
run_with_report(
    ctx=command_ctx,
    command_name="mapping",
    opts=opts,
    handler=mapping_command.handler,
    requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
)
```

**Зачем**: убирает дублирование логирования/отчётов/обработки ошибок во всех командах.

#### Паттерн 5: Guard Clauses

**Где применяется**: `_validate_requirements(...)` line 277 и `_require_*` методы в `runtime.py`.

**Реализация в коде**:
- требования описываются в `Requirements`;
- при нарушении precondition — `RuntimeErrorWithCode`.

**Пример использования**:
```python
if requirements.requires_source:
    _require_source(dataset)
```

**Зачем**: fail-fast до старта бизнес-логики команды.

### Диаграмма зависимостей

```
[CLI options + ENV + config.yml]
              ↓
   [load_settings_model()]
              ↓
 [LoadedSettings: settings + trace + warnings]
              ↓
    [load_app_settings()]
              ↓
 [LoadedAppSettings / AppSettings slices]
              ↓
   [app.py main + _build_ctx]
              ↓
 [CommandContext + Requirements]
              ↓
 [run_with_report / run_without_report]
              ↓
 [Command handler] → [UseCase] → [Domain/Infra]
              ↓
 [Diagnostics adapter + report artifacts]
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс/контракт | Назначение | Где используется |
|--------------------|-----------|------------------|
| `Requirements` | Декларация preconditions команды | `app.py`, `runtime.py` |
| `CommandContext` | Контекст исполнения команды | `delivery/commands/*` |
| `settings_slice_map` | Contract map command/use-case -> slices | `_build_ctx`, архитектурные тесты |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `Settings` | Flat-модель всех параметров | используется в `load_settings_model()` |
| `LoadedSettings` | Результат merge/parse/validate | возвращается `load_settings_model()` |
| `AppSettings` | Срезанная модель настроек | строится в `load_app_settings()` |
| `LoadedAppSettings` | `AppSettings` + source metadata | возвращается `load_app_settings()` |
| `SettingsIssue` | Field-level issue | используется parser/validator/adapter |
| `SettingsLoadError` и наследники | Типизированные ошибки загрузки | `app.py`, `runtime.py` |
| `RuntimeErrorWithCode` | Controlled runtime failure | `runtime.py` |

---

## 🗂️ Модели данных

### Dataclass: `Settings`

**Назначение**: Каноническая flat-конфигурация всех параметров приложения.

**Структура**:
```python
@dataclass(frozen=True)
class Settings:
    host: str | None = None
    port: int | None = None
    api_username: str | None = None
    api_password: str | None = None

    cache_dir: str = "./cache"
    log_dir: str = "./logs"
    report_dir: str = "./reports"

    page_size: int = 200
    retries: int = 3
    diagnostics_strict: bool = False
    # ...остальные поля
```

**Создание и использование**:
```python
loaded = load_settings_model(config_path=config_path, cli_overrides=cli_overrides)
settings = loaded.settings
```

**Lifecycle**:
1. **Создание**: после merge chain в `load_settings_model()`.
2. **Трансформации**: immutable (`frozen=True`), не мутируется.
3. **Завершение**: преобразуется в slices через `load_app_settings()`.

**Инварианты**:
- `host` и `port` задаются парой;
- `pending_on_expire` принадлежит enum;
- диапазонные инварианты проверяются `_validate_settings()`.

### Dataclass: `AppSettings` и slices

**Назначение**: Профильная runtime-модель, которая передаётся в команды/use-cases.

**Структура**:
```python
@dataclass(frozen=True)
class AppSettings:
    api: ApiSettings
    paths: PathsSettings
    observability: ObservabilitySettings
    dataset: DatasetSettings
    execution: ExecutionSettings
    refresh: RefreshSettings
    matching_runtime: MatchingRuntimeSettings
    pending: PendingSettings
```

**Создание и использование**:
```python
loaded_app = load_app_settings(config_path=config_path, cli_overrides=cli_overrides)
app_settings = loaded_app.app_settings
timeout = app_settings.api.timeout_seconds
```

**Lifecycle**:
1. **Создание**: `load_app_settings()` line 160.
2. **Трансформации**: immutable.
3. **Завершение**: хранится в `CommandContext.app_settings`.

**Инварианты**:
- slice содержит только профильные поля;
- покрытие полей закреплено тестом полноты (`test_settings_slice_completeness.py`).

### Dataclass: `CommandContext`

**Назначение**: Единый runtime-контейнер выполнения команды.

**Структура**:
```python
@dataclass(frozen=True)
class CommandContext:
    logger: logging.Logger
    run_id: str
    catalog: ErrorCatalog
    strict: bool
    app_settings: AppSettings
    paths: CommandPaths | None = None
    extra: dict[str, Any] | None = None
```

**Создание и использование**:
```python
command_ctx = _build_ctx(ctx, dataset, command_key="mapping")
run_with_report(ctx=command_ctx, command_name="mapping", opts=opts, ...)
```

**Lifecycle**:
1. **Создание**: `_build_ctx()` line 47.
2. **Трансформации**: в runtime может заменяться через `replace(ctx, logger=logger)`.
3. **Завершение**: живёт в рамках одной команды.

**Инварианты**:
- `app_settings` обязателен;
- `run_id` стабилен на весь lifecycle команды;
- `catalog` соответствует выбранному dataset/strict mode.

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `load_settings_model()` | ~161-247 | O(F) | Merge/parse/validate flat settings |
| `run_with_report()` | ~47-170 | O(1)+handler | Единый runtime lifecycle команды |
| `_validate_requirements()` | ~277-295 | O(1) | Проверка runtime preconditions |

где `F` — число полей `Settings`.

### Метод: `load_settings_model()`

**Расположение**: `connector/config/config.py:161`

**Сигнатура**:
```python
def load_settings_model(config_path: str | None, cli_overrides: dict[str, Any]) -> LoadedSettings:
```

**Назначение**: собрать итоговую settings-модель из нескольких источников и вернуть typed результат или typed ошибку.

**Алгоритм**:
```
1. Init defaults/specs (lines 177-180)
2. Load config source (lines 181-184)
3. Read env/cli raw values (lines 185-187)
4. Resolve unknown-keys policy (lines 188-195)
5. Apply sources in order: config -> env -> cli (lines 201-227)
6. If parse issues: raise SettingsParseError (lines 229-230)
7. Build Settings and validate invariants (lines 232-240)
8. Build source trace and return LoadedSettings (lines 241-247)
```

**Временная сложность**:
- **Best case**: O(F) — все значения валидны, warning/error нет.
- **Average case**: O(F) — типичный merge/parse по всем полям.
- **Worst case**: O(F) — с накоплением parse issues, без асимптотического роста.

**Инварианты**:
1. При parse/validation-conflict возвращается исключение, а не частичный результат.
2. Merge-порядок фиксирован: `defaults -> config -> env -> cli`.
3. В `source_trace` есть запись для каждого поля `Settings`.

**Edge cases**:
1. Некорректный YAML путь → `SettingsSourceError`.
2. Unknown keys + `diagnostics_strict=true` → `SettingsValidationError`.
3. Пустые env-значения (`""`) трактуются как `None`.

**Связанные методы**:
- `_apply_source()` `connector/config/config.py:337`.
- `_validate_settings()` `connector/config/config.py:500`.

### Метод: `run_with_report()`

**Расположение**: `connector/delivery/cli/runtime.py:47`

**Сигнатура**:
```python
def run_with_report(
    *,
    ctx: CommandContext,
    command_name: str,
    opts: Any,
    handler: ReportHandler,
    requirements: Requirements,
) -> None:
```

**Назначение**: исполнить команду в едином runtime lifecycle с логом, отчётом, валидацией prereq и стандартным обработчиком ошибок.

**Алгоритм**:
```
1. Resolve app_settings and create command logger (lines 62-71)
2. Create report envelope and set report metadata (lines 73-92)
3. Redirect stdout/stderr to logging streams (lines 94-100)
4. Validate requirements and call handler (lines 106-111)
5. Handle known errors (SettingsLoadError, DslLoadError, RuntimeErrorWithCode) (lines 113-152)
6. Finalize report, restore std streams, exit with computed code (lines 157-173)
```

**Временная сложность**:
- **Best case**: O(1)+`handler` — runtime overhead константный.
- **Average case**: O(1)+`handler`.
- **Worst case**: O(1)+`handler` + обработка ошибок/диагностик.

**Инварианты**:
1. Std streams восстанавливаются в `finally` независимо от исхода.
2. Report финализируется всегда (даже при исключениях).
3. Exit code вычисляется в одном месте через `_exit_code_from_result`.

**Edge cases**:
1. Ошибка загрузки settings внутри команды → diagnostics + FAILED item в отчёте.
2. DSL load error → diagnostics + code в meta отчёта.
3. Неожиданная ошибка handler → `SystemErrorCode.INTERNAL_ERROR`.

**Связанные методы**:
- `_validate_requirements()` `connector/delivery/cli/runtime.py:277`.
- `_call_handler()` (внутри `runtime.py`).
- `run_without_report()` для команд без отчёта.

### Метод: `_validate_requirements()`

**Расположение**: `connector/delivery/cli/runtime.py:277`

**Сигнатура**:
```python
def _validate_requirements(ctx: CommandContext, opts: Any, requirements: Requirements) -> None:
```

**Назначение**: fail-fast проверка runtime preconditions перед запуском handler.

**Алгоритм**:
```
1. Resolve app_settings from context
2. Check requires_api -> _require_api
3. Resolve dataset if needed
4. Check requires_cache / requires_secrets / requires_dataset / requires_source
5. Raise RuntimeErrorWithCode on first violated precondition
```

**Временная сложность**:
- **Best/Average/Worst**: O(1) для локальных проверок + стоимость `_require_source` (DSL source lookup).

**Инварианты**:
1. Handler не вызывается при нарушенном requirement.
2. Проверки выполняются до основной бизнес-логики.

**Edge cases**:
1. Dataset не задан при `requires_source=True`.
2. Source spec отсутствует для dataset.
3. Vault/secrets файл не задан при `requires_secrets=True`.

**Связанные методы**:
- `_require_source()` `connector/delivery/cli/runtime.py:305`.
- `_require_api()` `connector/delivery/cli/runtime.py:332`.
- `_require_cache()` `connector/delivery/cli/runtime.py:347`.

---

## 🛠️ Как расширять

### Добавить новое поле настройки

1. **Добавить поле в `Settings`** (`connector/config/config.py`):
   ```python
   @dataclass(frozen=True)
   class Settings:
       request_jitter_seconds: float = 0.0
   ```

2. **Добавить mapping в slice** (`connector/config/app_settings.py`):
   ```python
   _SLICE_FIELD_MAP[ApiSettings]["request_jitter_seconds"] = "request_jitter_seconds"
   ```

3. **(Опционально) добавить инвариант** (`connector/config/config.py`):
   ```python
   _RANGE_RULES.append(
       ("request_jitter_seconds", ">=0", "request_jitter_seconds must be >= 0", "Укажите неотрицательное значение.")
   )
   ```

### Добавить новый slice

1. **Создать dataclass slice** в `app_settings.py`:
   ```python
   @dataclass(frozen=True)
   class SecuritySettings:
       diagnostics_strict: bool
       tls_skip_verify: bool
   ```

2. **Включить в `AppSettings`**:
   ```python
   @dataclass(frozen=True)
   class AppSettings:
       # ...
       security: SecuritySettings
   ```

3. **Добавить mapping и сборку**:
   ```python
   _SLICE_FIELD_MAP[SecuritySettings] = {
       "diagnostics_strict": "diagnostics_strict",
       "tls_skip_verify": "tls_skip_verify",
   }
   ```

### Добавить новую CLI-команду с корректным settings-contract

1. **Зарегистрировать контракт slices** (`settings_slice_map.py`):
   ```python
   COMMAND_SETTINGS_SLICE_MAP["sync-preview"] = (
       DatasetSettings,
       ExecutionSettings,
       ObservabilitySettings,
       PathsSettings,
   )
   COMMAND_TO_USECASE["sync-preview"] = "SyncPreviewUseCase"
   ```

2. **Подключить команду в `app.py`**:
   ```python
   @app.command("sync-preview")
   def sync_preview(ctx: typer.Context, dataset: str | None = cli_options.DATASET):
       opts = sync_preview_command.Options(dataset=dataset)
       command_ctx = _build_ctx(ctx, dataset, command_key="sync-preview")
       run_with_report(
           ctx=command_ctx,
           command_name="sync-preview",
           opts=opts,
           handler=sync_preview_command.handler,
           requirements=Requirements(requires_dataset=True, requires_cache=True),
       )
   ```

### Добавить новый runtime requirement

1. **Расширить контракт** (`requirements.py`):
   ```python
   @dataclass(frozen=True)
   class Requirements:
       # ...
       requires_network: bool = False
   ```

2. **Добавить проверку в runtime** (`runtime.py`):
   ```python
   if requirements.requires_network:
       _require_network()
   ```

### Изменить policy обработки settings-ошибок

1. **Изменить adapter mapping** (`connector/config/diagnostics.py`):
   ```python
   def translate_settings_issue(...):
       # например, часть кодов переводить в warning
       ...
   ```

2. **Проверить runtime path** (`app.py`, `runtime.py`) и добавить/обновить тесты:
   - unit adapter tests;
   - integration settings errors tests;
   - architecture boundary tests.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Delivery CLI | Прямая зависимость | `load_app_settings`, `CommandContext`, `run_with_report` | Оркестрация команды |
| Use-cases | Передача настроек | `CommandContext.app_settings` | Передавать только нужные slices |
| Diagnostics | Adapter | `translate_settings_*` | Единый формат ошибок |
| DSL | Error integration | `DslLoadError` handling в `runtime.py` | Унифицированный error path |
| Infra | Wiring | `bootstrap.py` + slices | Создание runtime зависимостей |

---

## 🔌 Контракты и границы

### Runtime-контракт

```python
@dataclass(frozen=True)
class CommandContext:
    run_id: str
    app_settings: AppSettings
    catalog: ErrorCatalog
    strict: bool
```

**Гарантии**:
1. Handler получает `CommandContext` + `opts` (+ `report` в режиме с отчётом).
2. Full flat `Settings` не передаётся в команды/use-cases.
3. Diagnostics strictness определена до входа в handler.

### Границы слоёв

**Разрешенные зависимости** (что можно импортировать):
- ✅ `app.py` → `load_app_settings` — composition root создаёт full settings.
- ✅ `commands/*` → `CommandContext` — доступ к slices через контекст.
- ✅ `runtime.py` → `translate_settings_load_error` — единый diagnostic path.
- ✅ `settings_slice_map.py` → классы slices — декларация контрактов.

**Запрещенные зависимости** (нарушение архитектуры):
- ❌ `commands/usecases` → `Settings` из `connector.config.config`.
- ❌ legacy доступ `ctx.settings` или `ctx.obj["settings"]`.
- ❌ вызов `load_app_settings` вне composition root/config API.

**Архитектурные тесты**: `tests/architecture/config/test_settings_boundaries.py`

**Визуальная граница**:
```
┌─────────────────────────────────────────┐
│ CLI Composition Root (app.py)           │  ← full settings разрешены только здесь
└────────────▲────────────────────────────┘
             │ builds
┌────────────┴────────────────────────────┐
│ CommandContext + Runtime (cli/runtime)  │  ← slices only
└────────────▲────────────────────────────┘
             │ passes
┌────────────┴────────────────────────────┐
│ Commands / UseCases                     │  ← slices only, no flat Settings
└─────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Запуск команды с config + env + cli overrides

**Задача**: Запустить pipeline-команду, где часть параметров задана в `config.yml`, часть в ENV, часть в CLI.

**Решение**:
```python
loaded_app = load_app_settings(config_path=config, cli_overrides=cliOverrides)
command_ctx = _build_ctx(ctx, dataset, command_key="mapping")
run_with_report(
    ctx=command_ctx,
    command_name="mapping",
    opts=opts,
    handler=mapping_command.handler,
    requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
)
```

**Объяснение**: merge chain фиксированный, а в handler уходит только `CommandContext.app_settings`.

### Сценарий 2: Unknown keys в конфиге

**Задача**: Обработать лишние ключи в YAML без случайного падения в non-strict режиме.

**Решение**:
```python
strict_unknown = _resolve_strict_unknown(...)
unknown_issues = _collect_unknown_key_issues(...)
if strict_unknown and unknown_issues:
    raise SettingsValidationError(...)
warnings = [] if strict_unknown else unknown_issues
```

**Объяснение**: при `diagnostics_strict=false` ключи становятся warnings, при `true` — fail-fast.

### Сценарий 3: Runtime precondition не выполнен

**Задача**: Не запускать handler, если команда требует source, а source spec не настроен.

**Решение**:
```python
_validate_requirements(ctx, opts, requirements)
# внутри
if requirements.requires_source:
    _require_source(dataset)
```

**Объяснение**: guard clauses останавливают выполнение до старта бизнес-логики и возвращают контролируемый exit path.

---

## 📌 Важные детали

### Особенности реализации

- `Settings` и slices immutable (`frozen=True`), что упрощает предсказуемость runtime.
- Unknown key policy зависит от `diagnostics_strict` и вычисляется до merge этапа.
- В `run_with_report` std streams временно перенаправляются в logger и всегда восстанавливаются в `finally`.
- Контракт slices фиксируется явно в `settings_slice_map.py` и экспортируется в `ctx.extra["settings_contract"]`.

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `SettingsSourceError` | Некорректный путь/структура `config.yml` | Прерывание загрузки settings до запуска команды | Исправить путь/формат YAML |
| `SettingsParseError` | Невалидные типы полей (env/cli/config) | Агрегация field-level issues, завершение с diagnostics | Исправить типы значений в источниках |
| `SettingsValidationError` | Нарушены инварианты/unknown key в strict | Прерывание перед запуском handler | Исправить конфиг или отключить strict режим при необходимости |
| `SettingsConflictError` | Полуконфигурированный `host/port` | Прерывание перед runtime | Задать оба поля или убрать оба |
| `RuntimeErrorWithCode` | Не выполнены runtime requirements | Controlled exit до вызова handler | Донастроить dataset/source/cache/api/secrets |

### ⚠️ Инварианты системы

1. **Инвариант: Fixed merge order**
   - **Что**: `CLI > ENV > config > defaults` всегда неизменен.
   - **Почему важно**: определяет детерминированность конфигурации.
   - **Где проверяется**: `load_settings_model()` (`_apply_source` вызывается в фиксированном порядке).

2. **Инвариант: No flat settings below composition root**
   - **Что**: команды/use-cases не используют `Settings` напрямую.
   - **Почему важно**: изоляция слоя и контролируемые зависимости.
   - **Где проверяется**: `tests/architecture/config/test_settings_boundaries.py`.

3. **Инвариант: Context completeness**
   - **Что**: `CommandContext` всегда содержит `app_settings`, `run_id`, `catalog`.
   - **Почему важно**: runtime обвязка должна быть предсказуемой.
   - **Где проверяется**: `_build_ctx()` и runtime guards (`_require_app_settings`).

### ⏱️ Performance заметки

**Узкие места**:
1. **YAML + parse pipeline** (`load_settings_model`)
   - **Проблема**: линейная стоимость по количеству полей и источников.
   - **Текущая оптимизация**: единичный вызов на запуск процесса.

2. **Runtime wrapper overhead** (`run_with_report`)
   - **Проблема**: доп. логирование/репортинг на каждую команду.
   - **Текущая оптимизация**: единый общий каркас вместо дублирования по командам.

**Оптимизации**:
- централизованный parse/validate вместо разрозненных проверок по командам;
- fail-fast checks в `_validate_requirements`.

### Частые ошибки

- ❌ **Не делай так**: импортировать `Settings` в `delivery/commands` или `usecases`.
- ✅ **Делай так**: использовать `ctx.app_settings.<slice>`.

- ❌ **Не делай так**: вызывать `load_app_settings` внутри command handler.
- ✅ **Делай так**: вызывать только в `app.py` callback.

- ❌ **Не делай так**: добавлять новое поле в `Settings`, но не маппить в `_SLICE_FIELD_MAP`.
- ✅ **Делай так**: сразу обновлять mapping и тест полноты slices.

### Что нужно помнить

- Политика unknown keys зависит от `diagnostics_strict`.
- Все команды должны проходить через `run_with_report`/`run_without_report`.
- Границы settings слоя защищены архитектурными тестами — не обходить их локальными “быстрыми” решениями.

---

## 🔗 Связанные документы

- [Dev Index](../../INDEX.md)
- [Dev Template](../../TEMPLATE.md)
- [Method Documentation Guide](../../guides/method-documentation-template.md)
- [ADR: CONFIG-PROBLEM-001](../../../adr/config/CONFIG-PROBLEM-001-settings-layer-complexity.md)
- [ADR: CONFIG-DEC-001](../../../adr/config/CONFIG-DEC-001-modular-settings-and-slice-wiring.md)
- [UML: Config README](../../../uml/config/README.md)
- [UML: Global Style Template](../../../uml/TEMPLATE_STYLE.md)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-12 | Добавлен слой `AppSettings` со срезами | xORex-LC |
| 2026-02-12 | Введён канонический API `load_app_settings` | xORex-LC |
| 2026-02-12 | Добавлены typed settings errors и diagnostics adapter | xORex-LC |
| 2026-02-12 | Границы закреплены архитектурными тестами | xORex-LC |
| 2026-02-12 | Документация слоя синхронизирована с текущим кодом | xORex-LC |
