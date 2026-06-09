# Observability Config (Declarative Configuration)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🎯 Почему config, а не DSL](#-почему-config-а-не-dsl)
- [📊 Проекции config → policy](#-проекции-config--policy)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Декларативное описание поведения observability — вложенная Pydantic-секция
`observability` в `AppConfig`, плюс проекции этой секции в чистые value-policy объекты слоя
[model](./observability-model.md).

**Ключевая ответственность**: Задавать уровни/sink'и логирования, профиль отчётности, ретенцию,
diagnostics-strictness и backend ledger — и приводить их к domain-policy без утечки конфиг-моделей
в infra.

**Расположение в кодовой базе**:
- Схема: `connector/config/models.py` (`ObservabilityConfig` + подмодели, `PathsConfig`)
- Проекции: `connector/config/projections.py` (`to_observability_*`)
- Загрузка: общий `connector/config/loader.py` (см. [cli-settings-layer.md](../config/cli-settings-layer.md))

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/config/
├── models.py                  # вложенная схема observability (Pydantic, frozen, extra="forbid")
│   ├── ObservabilityConfig    # корень секции
│   ├── LoggingConfig          # level + components-override + redaction + sinks
│   │   ├── ComponentLoggingConfig    # per-component level override
│   │   ├── LoggingRedactionConfig    # enabled + keys
│   │   └── LoggingSinksConfig         # file + console
│   │       ├── FileLoggingSinkConfig    # format/rotation/max_bytes/retention_*
│   │       └── ConsoleLoggingSinkConfig # stream(stderr) + format(json)
│   ├── ReportingConfig        # format/policy_profile/items_limit/include_skipped/retention_days
│   ├── PlansConfig            # retention_days
│   ├── DiagnosticsConfig      # strict
│   ├── LedgerConfig           # enabled + backend(jsonl|sqlite)
│   └── PathsConfig            # cache_dir/log_dir/report_dir/plans_dir
└── projections.py             # config → policy/layout value objects
```

### 🎭 Применённые паттерны

#### Паттерн 1: Validated Settings (Pydantic v2)

**Где применяется**: вся секция `observability` — `BaseModel` с `model_config = ConfigDict(frozen=True,
extra="forbid")`. Неизвестные ключи и неверные типы отклоняются при загрузке (fail-fast).

**Зачем**: декларативность + строгая валидация + защита от опечаток в YAML.

#### Паттерн 2: Boundary Projection (config → domain policy)

**Где применяется**: `projections.py` приводит конфиг-модели к value-объектам
`ObservabilityLayoutPolicy` / `ObservabilityRedactionPolicy` / `ObservabilityLayout`.

**Реализация в коде**:
- `to_observability_layout_policy(config) -> ObservabilityLayoutPolicy`
- `to_observability_redaction_policy(config) -> ObservabilityRedactionPolicy`
- `to_observability_layout(config) -> ObservabilityLayout`

**Зачем**: infra/logging/artifacts зависят от **policy** (`common/`), а не от конфиг-моделей —
конфиг-слой не «протекает» внутрь.

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые поля |
|-------|------|---------------|
| `ObservabilityConfig` | Корень секции | `partition_by_component`, `clock`, `logging`, `reporting`, `plans`, `diagnostics`, `ledger` |
| `LoggingConfig` | Логирование | `level`, `components`, `redaction`, `sinks` |
| `ReportingConfig` | Отчётность | `format`, `policy_profile`, `items_limit`, `include_skipped`, `retention_days` |
| `PlansConfig` | Планы | `retention_days` |
| `DiagnosticsConfig` | Диагностика | `strict` |
| `LedgerConfig` | Run ledger | `enabled`, `backend` |
| `PathsConfig` | Рабочие каталоги | `cache_dir`, `log_dir`, `report_dir`, `plans_dir` |

---

## 🗂️ Модели данных

### Структура секции `observability` (YAML)

```yaml
observability:
  partition_by_component: true        # var/logs/<component>/... раскладка
  clock: utc                          # utc | local — TZ для имён файлов
  logging:
    level: INFO                       # DEBUG|INFO|WARNING|ERROR|CRITICAL
    components:                       # per-component override уровня (опционально)
      enricher: { level: DEBUG }
    redaction:
      enabled: true
      keys: [password, token, authorization, api_key, secret]   # DEFAULT_SENSITIVE_FIELD_KEYS
    sinks:
      file:
        enabled: true
        format: text                  # text | json
        rotation: hybrid              # daily | size | hybrid
        max_bytes: 104857600          # size-guard
        retention_days: 30
        retention_backups: 10
      console:
        enabled: true
        stream: stderr                # stderr | stdout (по умолчанию stderr)
        format: json                  # json | text
  reporting:
    format: json
    policy_profile: standard          # minimal | standard | debug
    items_limit: 200
    include_skipped: true
    retention_days: 30
  plans:
    retention_days: 30
  diagnostics:
    strict: false
  ledger:
    enabled: true
    backend: jsonl                    # jsonl | sqlite
```

**Инварианты**:
- Все подсекции `frozen=True, extra="forbid"` — неизвестные ключи отклоняются.
- `LoggingRedactionConfig.keys` принимает list или CSV-строку (`field_validator(mode="before")`).
- `components` — `dict[ServiceComponent, ComponentLoggingConfig]`; ключи YAML coerc-ятся в enum
  (неизвестный компонент → ошибка валидации, fail-fast).

### Связь с `PathsConfig`

`PathsConfig.plans_dir` (default `var/plans`) добавлен в Stage 1 рядом с существующими
`cache_dir/log_dir/report_dir`. Проецируется в `RuntimePaths.plans_root`, который потребляет
`ObservabilityLayout` (см. [model](./observability-model.md)).

---

## 🎯 Почему config, а не DSL

В отличие от `cache`/`target`/`topology`, у observability **нет YAML-DSL** (нет
spec→compiler→runtime-пайплайна). Причина:

- Observability — **cross-cutting инфраструктура**, а не датасет-специфичная трансформация. Её
  поведение задаётся **параметрами окружения/эксплуатации** (уровни, ротация, ретенция, транспорт),
  а не декларативными правилами обработки данных.
- Параметры стабильны и немногочисленны → строго типизированной Pydantic-секции достаточно; вводить
  отдельный DSL-движок было бы over-engineering (KISS).
- Нет потребности в пользовательских «операциях»/расширяемых правилах, ради которых существует DSL в
  других слоях.

Поэтому «декларативный контракт» observability — это **валидируемая config-секция**, а роль
«compiler» выполняют тонкие **проекции** (`projections.py`), приводящие config к domain-policy.

---

## 📊 Проекции config → policy

| Проекция | Вход | Выход | Используется |
|----------|------|-------|--------------|
| `to_observability_layout_policy` | `observability.{partition_by_component,clock}` | `ObservabilityLayoutPolicy` | layout |
| `to_observability_redaction_policy` | `observability.logging.redaction` | `ObservabilityRedactionPolicy` | `LogRedactionEngine` |
| `to_observability_layout` | runtime roots + layout policy | `ObservabilityLayout` | весь write/read/retention |
| `to_runtime_path_overrides` / `to_operational_paths` | `runtime` + `paths` (incl. `plans_dir`) | `RuntimePathOverrides` / `OperationalPaths` | резолв roots |

Прочие поля (`logging.level`, `logging.components`, `sinks.*`, `reporting.*`, `plans.retention_days`,
`ledger.*`, `diagnostics.strict`) потребляются напрямую в DI-контейнере и runtime-оркестраторе (см.
[observability-runtime.md](./observability-runtime.md)) — для них отдельная проекция не нужна.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| config/loader | Зависимость | `load_app_config` | загрузка/мердж/валидация (YAML+ENV+CLI) |
| common/observability | Производит | `to_observability_*` | policy/layout value-объекты |
| delivery/cli (DI) | Потребитель | `app_config.observability.*` | конфигурация logging_runtime, ledger, sweeper, reporting |

---

## 🔌 Контракты и границы

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `config/models.py` → `common/observability` (`ClockMode`, `ServiceComponent`), `common/sanitize`
- ✅ `config/projections.py` → `common/observability`, `common/runtime_paths`

**Запрещённые**:
- ❌ `config/*` → `infra/logging`, `infra/observability` (конфиг не зависит от исполнения)

**Ломающее изменение схемы (история)**: на Stage 1 плоская `ObservabilityConfig` была
реструктурирована во вложенные подсекции — это **намеренный чистый разрыв** (старые плоские YAML не
грузятся). Обоснование — в ADR
`OBSERVABILITY-DEC-002` и `CONFIG-DEC-*`; здесь — только «как сейчас».

---

## 💡 Типичные сценарии

### Сценарий 1: включить JSON в файловом sink и SQLite ledger

```yaml
observability:
  logging:
    sinks:
      file: { format: json }
  ledger: { backend: sqlite }
```

### Сценарий 2: точечный DEBUG только для enricher

```yaml
observability:
  logging:
    level: INFO
    components:
      enricher: { level: DEBUG }
```

---

## 📌 Важные детали

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| `ValidationError` | Неизвестный ключ / неверный тип / неизвестный компонент в `components` | Fail-fast при загрузке конфига | Исправить YAML по схеме |
| `SettingsLoadError` | Ошибка загрузки/мерджа config | Обрабатывается в оркестраторе как settings-error | См. [cli-settings-layer.md](../config/cli-settings-layer.md) |

### ⚠️ Инварианты системы

1. **Инвариант: строгая схема**
   - **Что**: все подсекции `frozen=True, extra="forbid"`.
   - **Почему важно**: опечатки и устаревшие ключи обнаруживаются сразу, а не молча игнорируются.
   - **Где проверяется**: Pydantic при `model_validate`.
2. **Инвариант: единый источник секретных ключей**
   - **Что**: `LoggingRedactionConfig.keys` и report-санитайзер используют `DEFAULT_SENSITIVE_FIELD_KEYS`.
   - **Почему важно**: одинаковое поведение redaction в логах и отчётах.
   - **Где проверяется**: `common/sanitize.py` (single source), потребители ссылаются на него.

### Что нужно помнить

- Дефолты подобраны так, чтобы значения сохраняли прежнее поведение; но **схема ломающая** —
  плоские ключи больше не принимаются.

---

## 🔗 Связанные документы

- [Observability Model](./observability-model.md) — policy/layout, которые получаются из config
- [Observability Logging](./observability-logging.md) / [Artifacts](./observability-artifacts.md) /
  [Runtime](./observability-runtime.md) — потребители config
- [CLI/Settings Layer](../config/cli-settings-layer.md) — общий loader/boundary
- ADR: `docs/adr/observability/OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md`

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002, Stage 1 nested config) | xorex-LC |
