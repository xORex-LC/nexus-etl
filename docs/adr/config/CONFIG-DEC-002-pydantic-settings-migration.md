# CONFIG-DEC-002: Миграция Settings на Pydantic — AppConfig(BaseModel) + unified loader

> **Статус**: Принято (реализация уточнена)
> **Дата принятия**: 2026-02-19
> **Дата уточнения**: 2026-02-26
> **Решает проблему**: [CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Текущий `Settings` — замороженный dataclass с ручной валидацией в `_validate_settings()`.
Pydantic уже используется в проекте. С добавлением `SqliteSettings` и других новых слайсов
стоимость сопровождения ручной валидации становится неоправданной
([CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md)).

### Текущее состояние (на момент уточнения)

В проекте существует **три независимых механизма загрузки конфигурации**:

1. **`Settings` (flat frozen dataclass, 37+ полей)** — ручная валидация через `_validate_settings()`,
   ручная коэрция типов (`_parse_int`, `_parse_float`, `_parse_bool`), manual range/enum checks
   через `_RANGE_RULES` и `_ENUM_RULES`.

2. **`AppSettings` (nested frozen dataclass, 9 slice-секций)** — слой поверх `Settings`,
   маппинг через `_SLICE_FIELD_MAP`, дублирование дефолтов.

3. **`SqliteSettings(BaseSettings)` / `DictionaryRuntimeSettings(BaseSettings)`** — автономные
   Pydantic-settings модели, загружаются контейнером (`containers.py`) напрямую из ENV,
   минуя единый pipeline загрузки.

Это создаёт три конкурирующих источника конфигурации и делает невозможным
единообразное добавление новых параметров.

---

## 🎯 Решение

Заменить все три механизма единой моделью `AppConfig(BaseModel)` с nested-секциями
и unified loader-функцией `load_app_config()`. Валидация становится декларативной
через типы Pydantic (`Literal`, `Field`). Трёхуровневый merge (CLI > ENV > config-file > defaults)
реализуется через явный loader, а не `settings_customise_sources()`.

### Ключевые решения

1. **`BaseModel`, не `BaseSettings`** — явный loader (`load_app_config()`) сохраняет source trace
   без борьбы с внутренним merge-механизмом pydantic-settings.

2. **Nested YAML** — config-файл повторяет структуру `AppConfig` 1:1. Clean break,
   без обратной совместимости с плоским форматом.

3. **ENV naming** — `ANKEY_{SECTION}__{FIELD}` (двойное подчёркивание `__` как разделитель уровней).
   Стандартная конвенция pydantic-settings.

4. **Unified loader** — `load_app_config()` заменяет и `load_settings_model()`, и `load_app_settings()`.

---

## 🏗️ Архитектурное решение

### Canonical model: AppConfig

```python
# connector/config/models.py (новый файл)
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

class ApiConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "localhost"
    port: int = Field(default=443, gt=0, le=65535)
    username: str = ""
    password_file: str = ""
    retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    # ... остальные api-поля


class SqliteConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] = "WAL"
    synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL"
    busy_timeout_ms: int = Field(default=5000, ge=1000, le=30000)
    wal_autocheckpoint: int = Field(default=1000, ge=0)
    vault_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "immediate"
    vault_busy_timeout_ms: int | None = Field(default=None, ge=1000, le=30000)
    vault_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
    vault_schema_retry_count: int = Field(default=2, ge=0, le=10)
    vault_db_path: str | None = None
    cache_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "deferred"
    cache_busy_timeout_ms: int | None = Field(default=None, ge=1000, le=30000)
    cache_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
    identity_db_path: str | None = None
    cache_db_path: str | None = None


class ResolverConfig(BaseModel):
    """Config-layer модель для resolver/pending механики.
    Projection в domain ResolverSettings через to_resolver_settings().
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_ttl_seconds: int = Field(default=120, gt=0)
    pending_max_attempts: int = Field(default=5, ge=0)
    pending_sweep_interval_seconds: int = Field(default=60, gt=0)
    pending_on_expire: Literal["drop", "keep", "error"] = "drop"
    pending_allow_partial: bool = False
    pending_retention_days: int = Field(default=7, ge=0)


class VaultRolloutConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["full", "canary", "off"] = "full"
    canary_percent: int = Field(default=100, ge=0, le=100)
    canary_datasets: list[str] = []
    canary_seed: str = ""
    row_failure_rate_threshold_pct: float = Field(default=10.0, ge=0, le=100)
    error_rate_threshold_pct: float = Field(default=5.0, ge=0, le=100)
    latency_regression_threshold_pct: float = Field(default=50.0, ge=0, le=100)
    busy_timeout_rate_threshold_pct: float = Field(default=5.0, ge=0, le=100)
    schema_changed_rate_threshold_pct: float = Field(default=1.0, ge=0, le=100)


class MatchingRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_batch_size: int = Field(default=500, gt=0)
    match_flush_interval_ms: int = Field(default=500, gt=0)
    resolve_batch_size: int = Field(default=500, gt=0)
    resolve_flush_interval_ms: int = Field(default=500, gt=0)


class DictionaryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["polars", "duckdb"] = "polars"
    max_rows: int = Field(default=100_000, gt=0)
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    parquet_row_group_size: int = Field(default=10_000, gt=0)
    compression: Literal["snappy", "zstd", "lz4", "none"] = "snappy"


# ... PathsConfig, ObservabilityConfig, DatasetConfig, ExecutionConfig, RefreshConfig ...


class AppConfig(BaseModel):
    """Каноническая модель конфигурации приложения.

    Единственный внутренний контракт для доставки настроек.
    Все user-facing параметры проходят через load_app_config() → AppConfig.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    api: ApiConfig = ApiConfig()
    paths: PathsConfig = PathsConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    dataset: DatasetConfig = DatasetConfig()
    execution: ExecutionConfig = ExecutionConfig()
    refresh: RefreshConfig = RefreshConfig()
    matching_runtime: MatchingRuntimeConfig = MatchingRuntimeConfig()
    resolver: ResolverConfig = ResolverConfig()
    sqlite: SqliteConfig = SqliteConfig()
    dictionary: DictionaryConfig = DictionaryConfig()
    vault_rollout: VaultRolloutConfig = VaultRolloutConfig()
```

### Nested YAML формат (config.yml)

```yaml
# config.yml — структура 1:1 с AppConfig
api:
  host: "idm.example.com"
  port: 443
  username: "sync-agent"
  retries: 3

sqlite:
  journal_mode: "WAL"
  synchronous: "NORMAL"
  busy_timeout_ms: 5000
  vault_transaction_mode: "immediate"

resolver:
  pending_ttl_seconds: 120
  pending_max_attempts: 5
  pending_on_expire: "drop"

vault_rollout:
  mode: "full"
  canary_percent: 100

matching_runtime:
  match_batch_size: 500
  resolve_batch_size: 500

dictionary:
  backend: "polars"
  max_rows: 100000
```

### ENV override naming

```bash
# Формат: ANKEY_{SECTION}__{FIELD}
# Двойное подчёркивание (__) как разделитель уровней

ANKEY_API__HOST=idm.example.com
ANKEY_API__PORT=443
ANKEY_SQLITE__JOURNAL_MODE=WAL
ANKEY_SQLITE__BUSY_TIMEOUT_MS=5000
ANKEY_RESOLVER__PENDING_TTL_SECONDS=120
ANKEY_VAULT_ROLLOUT__MODE=full
```

### Unified loader

```python
# connector/config/loader.py (новый файл)
from dataclasses import dataclass

@dataclass(frozen=True)
class LoadedAppConfig:
    """Результат загрузки конфигурации с диагностикой."""
    app_config: AppConfig
    source_trace: dict[str, str]   # "api.host" → "config" | "env" | "cli" | "default"
    warnings: list[SettingsIssue]

def load_app_config(
    config_path: str | None = None,
    cli_overrides: dict[str, object] | None = None,
) -> LoadedAppConfig:
    """Единственный production entrypoint загрузки конфигурации.

    Приоритет: CLI > ENV > config-file > defaults.
    """
    # 1. Читаем YAML (nested dict)
    raw = read_yaml_config(config_path) if config_path else {}

    # 2. Применяем ENV overrides (ANKEY_{SECTION}__{FIELD})
    merged, source_trace = _apply_env_overrides(raw)

    # 3. Применяем CLI overrides (dotted path: "api.host")
    merged, source_trace = _apply_cli_overrides(merged, cli_overrides or {}, source_trace)

    # 4. Pydantic validation
    app_config = AppConfig.model_validate(merged)

    return LoadedAppConfig(
        app_config=app_config,
        source_trace=source_trace,
        warnings=warnings,
    )
```

### Что удаляется

| Что | Где | Почему |
|-----|-----|--------|
| `_validate_settings()` | `config.py` | Заменяется Pydantic `Field(ge=..., le=...)`, `Literal[...]` |
| `_RANGE_RULES`, `_ENUM_RULES` | `config.py` | Декларативно в моделях |
| `_parse_int()`, `_parse_float()`, `_parse_bool()`, `_parse_str()` | `config.py` | Pydantic коэрция |
| `_build_field_specs()`, `_apply_source()` | `config.py` | Заменяется `load_app_config()` |
| `Settings` (flat frozen dataclass) | `config.py` | Заменяется `AppConfig(BaseModel)` |
| `AppSettings` (nested frozen dataclass) | `app_settings.py` | Заменяется `AppConfig(BaseModel)` |
| `_SLICE_FIELD_MAP` | `app_settings.py` | При nested YAML + nested model маппинг не нужен |
| `load_settings_model()` | `config.py` | Заменяется `load_app_config()` |
| `load_app_settings()` | `app_settings.py` | Заменяется `load_app_config()` |
| Slice-dataclasses (`ApiSettings`, `PathsSettings`, ...) | `app_settings.py` | Заменяются `*Config(BaseModel)` |
| `SqliteSettings(BaseSettings)` | `app_settings.py` | Заменяется `SqliteConfig` секцией `AppConfig` |
| `DictionaryRuntimeSettings(BaseSettings)` | `app_settings.py` | Заменяется `DictionaryConfig` секцией `AppConfig` |

### Что сохраняется

| Что | Где | Почему |
|-----|-----|--------|
| `SettingsIssue`, `SettingsLoadError` | `config.py` | Error-contract для диагностик |
| `read_yaml_config()` | `config.py` | Utility для чтения YAML |
| `env_get()` | `config.py` | Может использоваться в loader |
| `LoadedSettings` (→ `LoadedAppConfig`) | `config.py` | Паттерн сохраняется, тип переименуется |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Декларативность**: `Literal[...]` вместо `if val not in {...}`, `Field(ge=..., le=...)` вместо `if not (lo <= x <= hi)`
- ✅ **Автоматическая коэрция**: `"5000"` из ENV → `int 5000` без ручного кода
- ✅ **Единообразие**: Pydantic уже в проекте; Settings перестаёт быть исключением
- ✅ **IDE-поддержка**: `Literal` даёт autocomplete для enum-полей
- ✅ **Ошибки при старте**: Pydantic валидирует при инициализации модели, не в середине выполнения
- ✅ **Документируемость**: `AppConfig.model_json_schema()` → автогенерация схемы параметров деплоя
- ✅ **Source trace**: явный loader сохраняет информацию об источнике каждого поля
- ✅ **`extra="forbid"`**: опечатки в config.yml обнаруживаются сразу, а не молча игнорируются
- ✅ **Nested YAML**: структура конфига интуитивно понятна, 1:1 с моделью
- ✅ **Единый entrypoint**: одна функция `load_app_config()` вместо трёх конкурирующих loader'ов

**Недостатки (компромиссы)**:
- ⚠️ Clean break: плоский YAML перестаёт работать, требуется одномоментная миграция конфиг-файлов
- ⚠️ Объёмная работа: замена затрагивает `config.py`, `app_settings.py`, `containers.py`, все command handlers
- ⚠️ ENV naming меняется: `ANKEY_HOST` → `ANKEY_API__HOST` — требуется обновление деплой-скриптов

**Альтернативы, которые отклонили**:
- ❌ **`BaseSettings` вместо `BaseModel`**: автоматический merge через `settings_customise_sources()` не даёт контроля над source trace и усложняет отладку приоритетов
- ❌ **Частичный рефакторинг**: не решает фрагментацию (3 конкурирующих loader'а), не устраняет `_SLICE_FIELD_MAP`
- ❌ **Поэтапная миграция с backward compat**: двойной код на переходный период, сложность maintenance превышает стоимость clean break

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `pyproject.toml` / `requirements.txt` | `pydantic-settings` уже есть (используется `SqliteSettings`) |
| `connector/config/models.py` | **Новый**: все `*Config(BaseModel)` секции + `AppConfig` |
| `connector/config/loader.py` | **Новый**: `load_app_config()` — unified loader с source trace |
| `connector/config/projections.py` | **Новый**: централизованные проекции (см. CONFIG-DEC-003) |
| `connector/config/config.py` | Удалить `Settings`, `_validate_settings()`, manual parsers; оставить `SettingsIssue`, `SettingsLoadError`, `read_yaml_config()` |
| `connector/config/app_settings.py` | **Удалить целиком**: slice-dataclasses, `_SLICE_FIELD_MAP`, `load_app_settings()`, `SqliteSettings`, `DictionaryRuntimeSettings` |
| `connector/config/diagnostics.py` | Маппинг `pydantic.ValidationError` → `ConfigurationError` |
| `connector/delivery/cli/app.py` | CLI overrides в dotted-path формате: `{"api.host": host, "api.port": port}` |
| `connector/delivery/cli/context.py` | `app_settings: AppSettings` → `app_config: AppConfig` |
| `connector/delivery/cli/containers.py` | Удалить автономные `SqliteSettings()` / `DictionaryRuntimeSettings()`, получать секции из `AppConfig` |
| `connector/delivery/commands/*.py` | Заменить `app_settings.*` → `app_config.*` |
| `examples/configs/config_example.yml` | Переписать в nested формат со всеми секциями |

### Стратегия миграции

Миграция проводится **в одном PR**, clean break — `AppConfig` является центральной моделью,
частичная миграция создаёт несогласованность. Порядок внутри PR:

1. Создать `models.py` с `AppConfig` и всеми `*Config` секциями
2. Создать `loader.py` с `load_app_config()`
3. Создать `projections.py` с централизованными проекциями (CONFIG-DEC-003)
4. Обновить `containers.py`: удалить автономные `BaseSettings`, получать секции из `AppConfig`
5. Обновить CLI (`app.py`): dotted-path overrides
6. Обновить command handlers: `app_settings` → `app_config`
7. Обновить `config_example.yml` в nested формат
8. Удалить `Settings`, `_validate_settings()`, `_SLICE_FIELD_MAP`, manual parsers
9. Удалить `app_settings.py`
10. Обновить тесты

### Инварианты

1. Поведение конфигурации для существующих параметров не меняется (те же дефолты, тот же приоритет)
2. CLI-overrides имеют наивысший приоритет над ENV и config-файлом
3. Ошибки конфигурации выбрасываются при инициализации `AppConfig`, не при первом использовании поля
4. `extra="forbid"` на всех моделях: опечатки в YAML обнаруживаются сразу
5. Source trace сохраняется для каждого поля (`"config"` | `"env"` | `"cli"` | `"default"`)

---

## 🧪 Валидация решения

**Тесты**:
- `test_app_config_from_nested_yaml()` — nested YAML корректно парсится в `AppConfig`
- `test_app_config_env_override()` — `ANKEY_API__HOST` переопределяет YAML-значение
- `test_app_config_cli_override_beats_env()` — CLI override имеет приоритет над ENV
- `test_app_config_extra_forbid()` — неизвестный ключ в YAML вызывает `ValidationError`
- `test_app_config_invalid_literal()` — `ValidationError` при неизвестном значении enum
- `test_app_config_range_validation()` — `ValidationError` при выходе за диапазон (`Field(ge=..., le=...)`)
- `test_app_config_coercion()` — `"5000"` из ENV → `int 5000`
- `test_source_trace_preserved()` — `load_app_config()` корректно отслеживает источник каждого поля
- `test_app_config_defaults_match_current()` — regression: дефолты `AppConfig` совпадают с текущими `Settings`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/cli/app.py` | Прямое | CLI-overrides в dotted-path формате |
| `connector/delivery/cli/context.py` | Прямое | `app_settings` → `app_config` |
| `connector/delivery/cli/containers.py` | Прямое | Удалить `SqliteSettings()`/`DictionaryRuntimeSettings()`, получать секции `AppConfig` |
| `connector/delivery/commands/*` | Прямое | `app_settings.*` → `app_config.*` |
| `connector/config/diagnostics.py` | Прямое | Маппинг `pydantic.ValidationError` → `ConfigurationError` |
| Все тесты settings | Прямое | Обновить создание/использование конфига |
| `examples/configs/config_example.yml` | Прямое | Переписать в nested формат |
| Деплой-скрипты | Прямое | Обновить ENV naming: `ANKEY_HOST` → `ANKEY_API__HOST` |

---

## 🔗 Связанные документы

- [CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md) — решаемая проблема
- [CONFIG-DEC-001](./CONFIG-DEC-001-modular-settings-and-slice-wiring.md) — предыдущее решение (slice-архитектура заменяется nested AppConfig)
- [CONFIG-DEC-003](./CONFIG-DEC-003-settings-taxonomy-and-boundary-adapters.md) — таксономия и boundary adapters (projections, hidden defaults cleanup)
- [CACHE-DEC-002](../cache/CACHE-DEC-002-unified-sqlite-infra-layer.md) — `SqliteSettings` как первый pydantic-settings slice (войдёт в `SqliteConfig`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Решение принято при проектировании SqliteSettings; реализация отложена |
| 2026-02-26 | Уточнено: `BaseModel` вместо `BaseSettings`; nested YAML (clean break); `AppConfig` заменяет `Settings` + `AppSettings`; ENV naming `ANKEY_{SECTION}__{FIELD}`; unified loader `load_app_config()`; `extra="forbid"` |
