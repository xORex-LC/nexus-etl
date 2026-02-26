# CONFIG-DEC-003: Таксономия Settings и унификация конфигурационных границ/адаптеров

> **Статус**: Принято
> **Дата принятия**: 2026-02-24
> **Дата уточнения**: 2026-02-26
> **Решает проблему**: [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После `CONFIG-DEC-001` появился канонический app/CLI путь `load_app_settings(...)`, а после
`CONFIG-DEC-002` (уточнено 2026-02-26) зафиксирован переход на `AppConfig(BaseModel)` с nested YAML
и unified loader. При этом в проекте существуют параллельные settings-механизмы:

- `Settings` / `AppSettings` slices для user-facing конфигурации,
- `SqliteSettings` / `DictionaryRuntimeSettings` как отдельные runtime `BaseSettings`,
- доменные value-object'ы (`ResolverSettings`, `VaultRolloutPolicySettings`),
- component-local настройки (`HttpClientSettings` и др.).

В обсуждении выявлено, что корневая проблема не в самом факте существования нескольких типов
`*Settings`, а в отсутствии формально зафиксированного **единого пути доставки конфигурации**
и правил, где заканчивается:

- загрузка/парсинг/валидация,
- каноническая модель приложения,
- domain policy input,
- component-local runtime config.

Без этих правил контуры начинают расходиться по дефолтам, источникам значений и месту
преобразования (см. [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md)).

### Полная инвентаризация settings-моделей

**Config layer** (connector/config/) — **заменяются на AppConfig**:

| Модель | Тип | Полей | Судьба |
|--------|-----|-------|--------|
| `Settings` | flat frozen dataclass | 37+ | → `AppConfig(BaseModel)` |
| `AppSettings` | nested frozen dataclass | 9 секций | → `AppConfig(BaseModel)` |
| `ApiSettings`, `PathsSettings`, `ObservabilitySettings`, `DatasetSettings`, `ExecutionSettings`, `RefreshSettings`, `VaultRolloutSettings` | slice dataclasses | разн. | → `*Config(BaseModel)` секции |
| `MatchingRuntimeSettings` | slice dataclass | 4 | → `MatchingRuntimeConfig` (2 поля: только match); `resolve_batch_size`/`resolve_flush_interval_ms` → `ResolverConfig` |
| `SqliteSettings(BaseSettings)` | pydantic BaseSettings | 14 | → `SqliteConfig` секция `AppConfig` |
| `DictionaryRuntimeSettings(BaseSettings)` | pydantic BaseSettings | 5 | → `DictionaryConfig` секция `AppConfig` |

**Domain layer** (остаются без изменений):

| Модель | Тип | Полей | Файл |
|--------|-----|-------|------|
| `ResolverSettings` | frozen dataclass | 6 | `connector/domain/transform/resolver/resolve_deps.py` |
| `VaultRolloutPolicySettings` | frozen dataclass | 4 | `connector/domain/secrets/policy/rollout_policy.py` |
| `VaultRolloutThresholds` | frozen dataclass | 5 | `connector/domain/secrets/policy/rollout_metrics.py` |
| `MatchBatchSettings` | class | 2 | `connector/domain/transform/matcher/match_deps.py` |

**Infra layer** (остаются без изменений):

| Модель | Тип | Полей | Файл |
|--------|-----|-------|------|
| `SqliteDbConfig` | frozen dataclass | 7 | `connector/infra/sqlite/config.py` |
| `HttpClientSettings` | frozen dataclass | 14 | `connector/infra/target/transports/http/client_factory.py` |

### Выявленные проблемы

**Дублирование projections (3 копии `_rollout_settings`)**:
- `connector/delivery/commands/enrich.py:156-163`
- `connector/delivery/commands/import_plan.py:173-180`
- `connector/delivery/commands/import_apply.py:274-281`
- Плюс `_rollout_thresholds()` только в `import_apply.py:294-302`

**Hidden defaults в domain (расхождение с config-дефолтами)**:
- `resolve_core.py:588-595` — `_build_expires_at(None)` → `ttl=120`
- `resolve_core.py:598-601` — `_allow_partial(None)` → `False`
- `resolve_core.py:613-616` — `_max_attempts(None)` → `0` (**расхождение**: `Settings.pending_max_attempts` default=5)

**Параметры отсутствующие в config_example.yml**:
- `match_batch_size`, `match_flush_interval_ms`, `resolve_batch_size`, `resolve_flush_interval_ms`
- `vault_rollout_mode` и все `vault_rollout_*` поля
- `diagnostics_strict`
- Все `sqlite_*` поля (`SqliteSettings`)
- Все `dictionary_*` поля (`DictionaryRuntimeSettings`)

---

## 🎯 Решение

Зафиксировать **единый pipeline доставки конфигурации** и **единую каноническую модель приложения**
(`AppConfig`) как обязательный путь для всех user-facing параметров, а также правила для
производных локальных моделей в точках, где меняется смысл конфигурации.

Ключевые правила:

1. **Единый путь загрузки (обязательный)**
   Все user-facing параметры проходят путь: `CLI/ENV/config/default -> load_app_config() -> AppConfig`.
   Вторичных loader-путей в `containers.py`, command handlers и runtime-компонентах быть не должно.

2. **Одна каноническая app-модель**
   `AppConfig(BaseModel)` — единый внутренний контракт приложения (nested sections, frozen),
   из которого контейнер и слои получают настройки.

3. **Контейнер — "глупый" получатель зависимостей**
   DI-container не является loader'ом конфигурации и не должен самостоятельно инстанцировать
   settings-модели. Он получает `AppConfig` и извлекает из него секции/зависимости.

4. **Производные локальные модели допустимы только при смене смысла**
   Если конфигурация меняет архитектурную роль (например, превращается в effective DB config,
   transport config или policy input), создаётся отдельная локальная модель через projection.

5. **Domain policy settings не конкурируют с config-layer по дефолтам**
   Доменные `*Settings` остаются value-object'ами без собственных дефолтов.
   Дефолты живут в config-layer (`*Config` модели); domain получает готовые значения.
   Hidden fallbacks в domain удалены.

6. **Projections централизуются**
   Преобразования `AppConfig -> domain policy / component config` выполняются в одном модуле
   (`connector/config/projections.py`), а не дублируются в command handlers.

7. **ResolverConfig в config-слое**
   Конфигурация resolver/pending живёт в config-слое как `ResolverConfig(BaseModel)` с дефолтами.
   Projection `to_resolver_settings()` преобразует в domain `ResolverSettings(dataclass)`.
   Инвертированная зависимость (domain знает о defaults) устранена.

8. **Invocation intent не входит в `AppConfig`**
   Параметры, определяющие поведение *конкретного запуска*, а не деплоя, остаются в CLI-opts:
   `--vault-mode`, `--include-*-items`, per-run dataset override и т.п.

9. **Секретный материал не входит в `AppConfig`**
   Значения ключей/паролей/токенов остаются секретами.
   Допустимо хранить **пути** к файлам с секретами в `AppConfig`, но не сами секреты.

---

## 🏗️ Архитектурное решение

### Таксономия моделей (единый путь + разные роли)

1. **Config-layer models (граница источников)**
   - роль: декларативная конфигурация с валидацией и дефолтами
   - технология: `BaseModel` с `ConfigDict(frozen=True, extra="forbid")`
   - владелец: `connector/config/models.py`
   - примеры: `AppConfig`, `ApiConfig`, `SqliteConfig`, `ResolverConfig`, `VaultRolloutConfig`

2. **Canonical app model (`AppConfig`)**
   - роль: единый внутренний контракт приложения
   - технология: `BaseModel(frozen=True)` с nested секциями
   - владелец: `connector/config/models.py`
   - единственный entrypoint: `load_app_config()` из `connector/config/loader.py`

3. **Domain policy inputs (`ResolverSettings`, `VaultRolloutPolicySettings`, thresholds)**
   - роль: входы доменных policy/алгоритмов
   - технология: frozen dataclass (domain layer, без Pydantic зависимости)
   - владелец: domain слой
   - создаются через projection из `AppConfig`

4. **Component-local runtime configs (`SqliteDbConfig`, `HttpClientSettings`)**
   - роль: эффективная конфигурация конкретного компонента/транспорта
   - технология: frozen dataclass
   - владелец: infra компонент
   - создаются через projection из `AppConfig`

### Что не входит в `AppConfig` (и почему)

1. **Invocation intent (CLI-only опции)**
   Примеры: `--vault-mode`, `--include-*-items`, per-run dataset override.
   Причина: это *параметры конкретного запуска*, а не деплоя.

2. **Component-local effective configs**
   Примеры: `SqliteDbConfig`, `HttpClientSettings`.
   Причина: это вычисленные "effective" параметры, не исходные настройки.

3. **Секретный материал**
   Примеры: master keyring, токены, пароли.
   Допустимо хранить **пути к файлам** в `AppConfig`.

4. **DSL `location_ref` env-значения**
   `location_ref` — это runtime-resolution источника данных, а не app config.

### Централизованные projections

```python
# connector/config/projections.py (новый файл)
from connector.config.models import AppConfig
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.secrets.policy.rollout_policy import VaultRolloutPolicySettings
from connector.domain.secrets.policy.rollout_metrics import VaultRolloutThresholds
from connector.domain.transform.matcher.match_deps import MatchBatchSettings
from connector.infra.sqlite.config import SqliteDbConfig


def to_resolver_settings(config: AppConfig) -> ResolverSettings:
    """AppConfig.resolver → domain ResolverSettings."""
    r = config.resolver
    return ResolverSettings(
        pending_ttl_seconds=r.pending_ttl_seconds,
        pending_max_attempts=r.pending_max_attempts,
        pending_sweep_interval_seconds=r.pending_sweep_interval_seconds,
        pending_on_expire=r.pending_on_expire,
        pending_allow_partial=r.pending_allow_partial,
        pending_retention_days=r.pending_retention_days,
    )


def to_vault_rollout_policy_settings(config: AppConfig) -> VaultRolloutPolicySettings:
    """AppConfig.vault_rollout → domain VaultRolloutPolicySettings.

    canary_datasets: VaultRolloutConfig использует tuple[str, ...] — Pydantic v2
    автоматически coerce-ит YAML-list → tuple. Передаётся без конвертации.
    """
    vr = config.vault_rollout
    return VaultRolloutPolicySettings(
        mode=vr.mode,           # "full"|"canary"|"staging_dry_run"|"off"
        canary_percent=vr.canary_percent,
        canary_datasets=vr.canary_datasets,   # оба уже tuple[str, ...]
        canary_seed=vr.canary_seed,
    )


def to_vault_rollout_thresholds(config: AppConfig) -> VaultRolloutThresholds:
    """AppConfig.vault_rollout → domain VaultRolloutThresholds.

    Примечание по именам:
      VaultRolloutConfig.error_rate_threshold_pct
        → VaultRolloutThresholds.vault_error_rate_threshold_pct
    Префикс vault_ в доменной модели унаследован до унификации config-слоя.
    В VaultRolloutConfig он убран как несогласованный (был vault_error_rate* среди
    остальных полей без этого префикса).

    Примечание по дефолтам:
    VaultRolloutThresholds имеет собственные дефолты в домене (row=5.0, latency=15.0
    и т.д.) — они shadowed этой проекцией. Production defaults живут только в
    VaultRolloutConfig. В тестах, создающих VaultRolloutThresholds() напрямую,
    доменные дефолты используются для тест-изоляции, а не как production-values.
    """
    vr = config.vault_rollout
    return VaultRolloutThresholds(
        row_failure_rate_threshold_pct=vr.row_failure_rate_threshold_pct,
        # поле переименовано: убран prefix vault_ в config-модели
        vault_error_rate_threshold_pct=vr.error_rate_threshold_pct,
        latency_regression_threshold_pct=vr.latency_regression_threshold_pct,
        busy_timeout_rate_threshold_pct=vr.busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=vr.schema_changed_rate_threshold_pct,
    )


def to_match_batch_settings(config: AppConfig) -> MatchBatchSettings:
    """AppConfig.matching_runtime → domain MatchBatchSettings (match side only).

    Resolve batch-параметры (resolve_batch_size, resolve_flush_interval_ms) находятся
    в AppConfig.resolver и доставляются через DI-wiring напрямую — отдельного
    domain-порта IResolveBatchSettings пока нет.
    """
    mr = config.matching_runtime
    return MatchBatchSettings(
        batch_size=mr.match_batch_size,
        flush_interval_ms=mr.match_flush_interval_ms,
    )


def to_vault_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для vault DB."""
    s = config.sqlite
    return SqliteDbConfig(
        journal_mode=s.vault_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        busy_timeout_ms=s.vault_busy_timeout_ms or s.busy_timeout_ms,
        wal_autocheckpoint=s.wal_autocheckpoint,
        transaction_mode=s.vault_transaction_mode,
        schema_retry_count=s.vault_schema_retry_count,
        db_path=s.vault_db_path,
    )


def to_cache_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для cache DB."""
    s = config.sqlite
    return SqliteDbConfig(
        journal_mode=s.cache_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        busy_timeout_ms=s.cache_busy_timeout_ms or s.busy_timeout_ms,
        wal_autocheckpoint=s.wal_autocheckpoint,
        transaction_mode=s.cache_transaction_mode,
        db_path=s.cache_db_path,
    )


def to_identity_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для identity DB.

    schema_retry_count не включён намеренно: identity DB не использует
    schema migration с retry (в отличие от vault DB).
    """
    s = config.sqlite
    return SqliteDbConfig(
        journal_mode=s.journal_mode,
        synchronous=s.synchronous,
        busy_timeout_ms=s.busy_timeout_ms,
        wal_autocheckpoint=s.wal_autocheckpoint,
        db_path=s.identity_db_path,
    )
```

### Hidden defaults cleanup

`ResolveCore.__init__` принимает `settings: ResolverSettings` как **обязательный** параметр
(не `Optional`). Скрытые fallbacks удалены:

```python
# БЫЛО (resolve_core.py):
def _build_expires_at(settings: ResolverSettings | None):
    if settings is None: ttl = 120          # hidden default
def _allow_partial(settings: ResolverSettings | None):
    if settings is None: return False       # hidden default
def _max_attempts(settings: ResolverSettings | None):
    if settings is None: return 0           # BUG: diverges from Settings default=5!

# СТАЛО:
class ResolveCore:
    def __init__(self, settings: ResolverSettings, ...):  # non-optional
        ...
# Дефолты живут только в ResolverConfig (config layer)
```

### Поток данных (целевое состояние)

```
[CLI args]   [ENV vars]   [config.yml (nested)]   [defaults in *Config models]
    \           |               /                        /
     \          |              /                        /
      +---------+-------------+------------------------+
                        |
                        v
        load_app_config(...)  # parse + validate + source-trace
                        |
                        v
             AppConfig (canonical model, frozen)
             ├── api: ApiConfig
             ├── paths: PathsConfig
             ├── sqlite: SqliteConfig
             ├── resolver: ResolverConfig
             ├── vault_rollout: VaultRolloutConfig
             ├── matching_runtime: MatchingRuntimeConfig
             ├── dictionary: DictionaryConfig
             └── ...
                        |
            +-----------+---------------+
            |                           |
            v                           v
   DI Container                 projections.py
   (consumer only)              (centralized)
   - получает AppConfig         |
   - НЕ создает settings        +--→ to_resolver_settings()        → ResolverSettings
   - передает секции             +--→ to_vault_rollout_policy()     → VaultRolloutPolicySettings
     в субконтейнеры             +--→ to_vault_rollout_thresholds() → VaultRolloutThresholds
            |                    +--→ to_vault_db_config()          → SqliteDbConfig
            |                    +--→ to_cache_db_config()          → SqliteDbConfig
            |                    +--→ to_match_batch_settings()     → MatchBatchSettings
            |
            | DI wiring (без projection — нет domain-порта):
            +--→ app_config.resolver.resolve_batch_size        → resolver infra
            v   app_config.resolver.resolve_flush_interval_ms
   usecases / stages
```

### Когда нужен projection

```
AppConfig секция ──► Можно передать как есть?
                     │
                     ├─ Да ─► Передаём напрямую
                     │       (semantics unchanged, тот же owner)
                     │
                     └─ Нет ─► Почему?
                              - changed owner? (config → domain)
                              - computed/effective values?
                              - split into multiple inputs?
                              - consumer-specific invariants?
                              │
                              └─► Делаем projection
                                  в projections.py
```

### Пример использования в composition root

```python
# Bootstrap / composition root (целевое состояние)
loaded = load_app_config(config_path=config_path, cli_overrides=cli_overrides)
app_config = loaded.app_config

container = AppContainer()
container.app_config.override(providers.Object(app_config))
container.init_resources()

# Container reads sections from canonical model (НЕ создает settings сам)
# sqlite = providers.Callable(lambda c: c.sqlite, c=app_config)

# Command handlers use centralized projections
rollout_policy = to_vault_rollout_policy_settings(ctx.app_config)
thresholds = to_vault_rollout_thresholds(ctx.app_config)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Один обязательный pipeline доставки конфигурации для всех user-facing параметров
- ✅ `AppConfig` — единая каноническая модель вместо трёх конкурирующих entrypoints
- ✅ Устраняет автономную загрузку settings в контейнере (`SqliteSettings()`, `DictionaryRuntimeSettings()`)
- ✅ Устраняет дублирующие `_rollout_settings()` в 3 command handlers
- ✅ Устраняет hidden defaults в domain (расхождение `_max_attempts(None)→0` vs `pending_max_attempts=5`)
- ✅ Чётко разделяет: config model / app model / domain policy input / component-local config
- ✅ Добавление нового параметра: один файл (`models.py`) + один YAML + projection при необходимости
- ✅ `config_example.yml` в nested формате содержит ВСЕ параметры (sqlite, dictionary, vault_rollout, matching_runtime)

**Недостатки (компромиссы)**:
- ⚠️ Projections создают дополнительный маппинг-слой между config и domain
- ⚠️ Требует дисциплины и архитектурных тестов, иначе container/commands начнут создавать свои loader-пути
- ⚠️ Миграция затрагивает `config`, `containers.py` и все command handlers одновременно

**Альтернативы, которые отклонили**:
- ❌ **Оставить текущий split и только документировать**: не устраняет hidden defaults, автономную загрузку в контейнере и дублирующие projections
- ❌ **"Одна модель для всего" (включая доменные/infra локальные конфиги)**: смешивает роли и размывает архитектурные границы
- ❌ **Поэтапная миграция с backward compat**: двойной код на переходный период; clean break менее рискован

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/config/models.py` | **Новый**: `AppConfig`, `ResolverConfig`, `VaultRolloutConfig`, `MatchingRuntimeConfig`, `DictionaryConfig`, `SqliteConfig` и другие секции |
| `connector/config/loader.py` | **Новый**: `load_app_config()` — unified loader |
| `connector/config/projections.py` | **Новый**: `to_resolver_settings()`, `to_vault_rollout_policy_settings()`, `to_vault_rollout_thresholds()`, `to_match_batch_settings()`, `to_vault_db_config()`, `to_cache_db_config()`, `to_identity_db_config()` |
| `connector/config/app_settings.py` | **Удалить**: slice-dataclasses, `_SLICE_FIELD_MAP`, `SqliteSettings(BaseSettings)`, `DictionaryRuntimeSettings(BaseSettings)`, `load_app_settings()` |
| `connector/delivery/cli/containers.py` | Удалить `_sqlite_cfg = providers.Singleton(SqliteSettings)` и `_dictionary_cfg = providers.Singleton(DictionaryRuntimeSettings)`; получать секции из `AppConfig` |
| `connector/delivery/commands/enrich.py` | Удалить `_rollout_settings()`, использовать `to_vault_rollout_policy_settings()` из `projections.py` |
| `connector/delivery/commands/import_plan.py` | Удалить `_rollout_settings()`, использовать projection |
| `connector/delivery/commands/import_apply.py` | Удалить `_rollout_settings()` и `_rollout_thresholds()`, использовать projections |
| `connector/domain/transform/resolver/resolve_core.py` | `settings: ResolverSettings` обязательный (non-optional); удалить `_build_expires_at(None)`, `_allow_partial(None)`, `_max_attempts(None)` fallbacks |
| `connector/delivery/cli/context.py` | `app_settings: AppSettings` → `app_config: AppConfig` |
| `examples/configs/config_example.yml` | Переписать в nested формат со всеми секциями |
| `tests/architecture/config/test_settings_boundaries.py` | Guardrails: единый pipeline, запрет автономных loader-path |

### План перехода

Реализация выполняется совместно с CONFIG-DEC-002 **в одном PR** (clean break):

1. **Создать новые модули config-layer**
   - `models.py`: `AppConfig` и все `*Config` секции с Pydantic валидацией и дефолтами
   - `loader.py`: `load_app_config()` с source trace
   - `projections.py`: централизованные проекции

2. **Обновить DI-контейнер**
   - `containers.py`: удалить автономные `SqliteSettings()`/`DictionaryRuntimeSettings()`
   - Получать секции через `AppConfig`

3. **Обновить command handlers**
   - Заменить `_rollout_settings()` на `to_vault_rollout_policy_settings()`
   - Заменить `_rollout_thresholds()` на `to_vault_rollout_thresholds()`
   - `app_settings` → `app_config`

4. **Resolver hidden defaults cleanup**
   - `ResolveCore.__init__`: `settings: ResolverSettings` (non-optional)
   - Удалить `_build_expires_at(None)`, `_allow_partial(None)`, `_max_attempts(None)`

5. **Обновить CLI и context**
   - `app.py`: dotted-path CLI overrides
   - `context.py`: `app_config: AppConfig`

6. **Удалить старый код**
   - `config.py`: `Settings`, `_validate_settings()`, manual parsers
   - `app_settings.py`: целиком

7. **Обновить конфиг и тесты**
   - `config_example.yml`: nested формат со всеми секциями
   - Архитектурные тесты: guardrails

### Инварианты

1. **Все user-facing настройки проходят через `load_app_config()`.**
2. **`AppConfig` — единственный канонический контракт приложения для доставки настроек.**
3. **DI-контейнер не инстанцирует settings-модели; получает `AppConfig` и извлекает секции.**
4. **Projections создаются только при смене смысла конфигурации (config→domain, config→infra effective).**
5. **Domain policy settings не содержат hidden defaults. Все дефолты в config-layer `*Config` моделях.**
6. **Component-local configs не становятся вторым глобальным settings-entrypoint.**
7. **Секретный материал не хранится в `AppConfig`; допустимы только пути/идентификаторы.**
8. **`extra="forbid"` на всех `*Config` моделях: опечатки обнаруживаются при загрузке.**

---

## 🧪 Валидация решения

### Полная матрица: delete / update / add

#### Удаляются (5 файлов)

| Файл | Причина |
|------|---------|
| `tests/unit/config/test_settings_validation.py` | Тестирует `_validate_settings()` → удаляется вместе с функцией |
| `tests/unit/config/test_settings_merge.py` | Тестирует `_apply_source()`, `_build_field_specs()` → удаляются |
| `tests/unit/config/test_settings_parsing.py` | Тестирует `_parse_bool()`, `_parse_int()`, `_parse_float()` → удаляются |
| `tests/unit/config/test_settings_slice_completeness.py` | Тестирует `_SLICE_FIELD_MAP` → удаляется |
| `tests/unit/config/test_sqlite_settings.py` | Тестирует `SqliteSettings(BaseSettings)` как standalone → удаляется |

#### Обновляются / переписываются (7 файлов)

| Файл | Действие | Ключевые изменения |
|------|----------|--------------------|
| `tests/unit/config/test_settings_diagnostics_adapter.py` | Без изменений (KEEP) | `translate_settings_issue()` не меняется |
| `tests/unit/config/test_runtime_settings_boundary.py` | Переписать | `AppSettings` со slice-конструктором → `AppConfig` с nested секциями |
| `tests/unit/config/test_config_priority.py` | Переписать | Плоский YAML + `ANKEY_HOST` → nested YAML + `ANKEY_API__HOST`; `load_app_settings()` → `load_app_config()` |
| `tests/unit/config/test_settings_errors.py` | Переписать | `extra="forbid"` → неизвестный ключ **всегда** `ValidationError` (нет режима "warn"); удалить `test_unknown_keys_warn_by_default` / `test_unknown_keys_error_in_strict_mode`; заменить на `test_unknown_key_always_raises_validation_error` |
| `tests/architecture/config/test_settings_boundaries.py` | Обновить + добавить guardrails | Добавить 4 новых guardrail (см. ниже) |
| `tests/integration/config/test_settings_runtime_boundary.py` | Обновить | Плоский YAML `host: "1.1.1.1"` → nested YAML `api:\n  host: "1.1.1.1"` |
| `tests/e2e/cli/test_settings_cli_smoke.py` | Обновить | Плоский YAML → nested YAML в `cfg.write_text(...)` |

#### Добавляются (3 новых файла)

| Файл | Содержание |
|------|------------|
| `tests/unit/config/test_app_config_models.py` | Модели `AppConfig`, `*Config`: defaults, validation, frozen, extra="forbid", Pydantic coerce |
| `tests/unit/config/test_app_config_loader.py` | `load_app_config()`: nested YAML, ENV override, CLI priority, source trace |
| `tests/unit/config/test_config_projections.py` | Все projection-функции из `projections.py` |

*(Спецификации `test_app_config_models.py` и `test_app_config_loader.py` — см. [CONFIG-DEC-002](./CONFIG-DEC-002-pydantic-settings-migration.md), раздел «🧪 Валидация решения»)*

### Тесты: `tests/unit/config/test_config_projections.py` (новый)

```
test_to_resolver_settings_maps_all_fields()
  — все 6 полей ResolverConfig → ResolverSettings переданы корректно

test_to_resolver_settings_default_values_match_config_defaults()
  — ResolverConfig() → ResolverSettings: pending_max_attempts=5, pending_ttl_seconds=120

test_to_vault_rollout_policy_settings_mode_literal()
  — mode="staging_dry_run" → VaultRolloutPolicySettings.mode="staging_dry_run"

test_to_vault_rollout_policy_settings_canary_datasets_tuple()
  — canary_datasets=("ds1", "ds2") → VaultRolloutPolicySettings.canary_datasets == ("ds1", "ds2")

test_to_vault_rollout_thresholds_renames_error_rate()
  — VaultRolloutConfig.error_rate_threshold_pct → VaultRolloutThresholds.vault_error_rate_threshold_pct

test_to_vault_rollout_thresholds_default_values()
  — дефолты из VaultRolloutConfig(): row=5.0, latency=15.0, busy=0.0, schema=0.0 (regression guard)

test_to_match_batch_settings_maps_match_fields()
  — match_batch_size, match_flush_interval_ms → MatchBatchSettings корректно

test_to_match_batch_settings_no_resolve_fields()
  — MatchBatchSettings не содержит resolve_batch_size / resolve_flush_interval_ms
    (они живут в ResolverConfig и доставляются через DI-wiring)

test_to_vault_db_config_uses_vault_override_when_set()
  — vault_busy_timeout_ms=1234 → SqliteDbConfig.busy_timeout_ms=1234

test_to_vault_db_config_falls_back_to_global()
  — vault_busy_timeout_ms=None → SqliteDbConfig.busy_timeout_ms = SqliteConfig.busy_timeout_ms

test_to_cache_db_config_deferred_transaction_mode()
  — SqliteDbConfig.transaction_mode == "deferred"

test_to_identity_db_config_no_schema_retry_field()
  — SqliteDbConfig для identity не содержит schema_retry_count
    (Identity DB не использует schema migration с retry)

test_to_identity_db_config_uses_global_defaults_only()
  — все поля из SqliteConfig глобального уровня (нет per-DB override для identity)
```

### Architecture guardrails: `tests/architecture/config/test_settings_boundaries.py` (добавить)

К существующим guardrails добавить 4 новых:

```
test_load_app_config_is_only_production_entrypoint()
  — containers.py и command handlers не содержат вызовов
    load_settings_model() / load_app_settings()
  — разрешён только load_app_config()

test_no_autonomous_base_settings_in_container()
  — containers.py не инстанцирует SqliteSettings() /
    DictionaryRuntimeSettings() / BaseSettings напрямую

test_no_duplicate_rollout_projections_in_command_handlers()
  — enrich.py / import_plan.py / import_apply.py не содержат
    локальных _rollout_settings() / _rollout_thresholds()
  — используют to_vault_rollout_policy_settings() /
    to_vault_rollout_thresholds() из projections.py

test_resolve_core_settings_non_optional()
  — сигнатура ResolveCore.__init__ содержит settings: ResolverSettings (не Optional)
  — вспомогательные функции _build_expires_at / _allow_partial /
    _max_attempts не принимают None
```

### Метрики успеха

| Метрика | Целевое значение |
|---------|-----------------|
| Автономные loader-path для settings в delivery/runtime | **= 0** |
| Дублирующие projection-функции в command handlers | **= 0** |
| Расхождения между дефолтами config-layer и domain runtime fallback | **= 0** |
| Тест-файлы, проверяющие удалённый код | **= 0** (5 файлов удаляются) |
| Projection-функции, покрытые unit-тестами | **= 100%** (7 функций в `test_config_projections.py`) |

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Clean break: плоский YAML перестаёт работать; требуется одномоментная миграция config-файлов
- ENV naming меняется: `ANKEY_HOST` → `ANKEY_API__HOST`; требуется обновление деплой-скриптов
- Hot reload параметров **не закладывается** в текущем решении (отдельный scope)

**Риски**:
- ⚠️ Риск 1: Объёмность миграции (config + containers + commands + tests в одном PR)
  → Митигация: чёткий план шагов внутри PR; промежуточные проверки тестами
- ⚠️ Риск 2: Удаление resolver hidden defaults может затронуть тесты, где `ResolveCore` создаётся без settings
  → Митигация: обновить тесты, создавая `ResolverSettings` с дефолтами из `ResolverConfig()`
- ⚠️ Риск 3: Перегиб в "projection everywhere" создаст лишнюю бюрократию
  → Митигация: projection разрешён только при подтверждённой смене смысла (по критериям из этого ADR)

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/config/` | Прямое | Новые `models.py`, `loader.py`, `projections.py`; удаление `app_settings.py` |
| `connector/delivery/cli/containers.py` | Прямое | Удалить автономные settings; получать секции из `AppConfig` |
| `connector/delivery/commands/*` | Прямое | Удалить дублирующие projections, использовать `projections.py` |
| `connector/domain/transform/resolver/*` | Прямое | `ResolverSettings` non-optional; удалить hidden defaults |
| `connector/delivery/cli/context.py` | Прямое | `app_settings` → `app_config` |
| `connector/delivery/cli/app.py` | Прямое | Dotted-path CLI overrides |
| `connector/infra/target/*` | Нет | `HttpClientSettings` строится infra-internally в `client_factory.py`; дублирования нет, централизация не нужна |
| `connector/delivery/cli/settings_slice_map.py` | Прямое | `*Settings` → `*Config`; `ResolverSettings` (domain) → `ResolverConfig` (config) |
| `examples/configs/config_example.yml` | Прямое | Переписать в nested формат |
| `tests/` | Прямое | Обновить все тесты settings, добавить architecture guardrails |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md)
- ✅ [CONFIG-DEC-003](./CONFIG-DEC-003-settings-taxonomy-and-boundary-adapters.md)
- ✅ [ADR Index](../INDEX.md) (раздел Config)

---

## 🔗 Связанные документы

- [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md) - решаемая проблема
- [CONFIG-DEC-001](./CONFIG-DEC-001-modular-settings-and-slice-wiring.md) - канонический slice-based wiring (заменяется nested AppConfig)
- [CONFIG-DEC-002](./CONFIG-DEC-002-pydantic-settings-migration.md) - стратегия миграции на Pydantic (AppConfig + unified loader)
- [TRANSFORM-DEC-004](../transform/TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) - typed capability context для стадий
- [DELIVERY-DEC-006](../delivery/DELIVERY-DEC-006-app-container-composition-root-integration.md) - `AppContainer` как composition root

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Решение предложено по итогам архитектурного обзора settings/config границ |
| 2026-02-24 | Уточнено после обсуждения: единый pipeline + canonical `AppSettings`; projections только при смене смысла |
| 2026-02-26 | Уточнено: `AppConfig(BaseModel)` заменяет `AppSettings`; `ResolverConfig` в config-слое с projection; `SqliteConfig`/`DictionaryConfig` как секции `AppConfig`; централизованные projections в `projections.py`; hidden defaults cleanup; полная инвентаризация settings-моделей; clean break без backward compat |
| 2026-02-26 | Исправлено по ревью: `staging_dry_run` в `mode` Literal; `canary_datasets: tuple[str, ...]` (Pydantic coerce); `canary_seed="vault-rollout-v1"`; threshold дефолты выровнены по текущим доменным; `resolve_batch_size`/`resolve_flush_interval_ms` перенесены в `ResolverConfig` (нет domain-порта — доставка через DI-wiring); `HttpClientSettings` остаётся infra-internal; `settings_slice_map.py` добавлен в impact table; причина rename `error_rate_threshold_pct` задокументирована; domain-дефолты `VaultRolloutThresholds` признаны shadowed проекцией |
