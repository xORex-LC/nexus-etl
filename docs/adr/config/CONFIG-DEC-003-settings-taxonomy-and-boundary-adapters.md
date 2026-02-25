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
| `ApiSettings`, `PathsSettings`, `ObservabilitySettings`, `DatasetSettings`, `ExecutionSettings`, `RefreshSettings`, `MatchingRuntimeSettings`, `VaultRolloutSettings` | slice dataclasses | разн. | → `*Config(BaseModel)` секции |
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
    """AppConfig.vault_rollout → domain VaultRolloutPolicySettings."""
    vr = config.vault_rollout
    return VaultRolloutPolicySettings(
        mode=vr.mode,
        canary_percent=vr.canary_percent,
        canary_datasets=vr.canary_datasets,
        canary_seed=vr.canary_seed,
    )


def to_vault_rollout_thresholds(config: AppConfig) -> VaultRolloutThresholds:
    """AppConfig.vault_rollout → domain VaultRolloutThresholds."""
    vr = config.vault_rollout
    return VaultRolloutThresholds(
        row_failure_rate_threshold_pct=vr.row_failure_rate_threshold_pct,
        vault_error_rate_threshold_pct=vr.error_rate_threshold_pct,
        latency_regression_threshold_pct=vr.latency_regression_threshold_pct,
        busy_timeout_rate_threshold_pct=vr.busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=vr.schema_changed_rate_threshold_pct,
    )


def to_match_batch_settings(config: AppConfig) -> MatchBatchSettings:
    """AppConfig.matching_runtime → domain MatchBatchSettings."""
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
    """AppConfig.sqlite → infra SqliteDbConfig для identity DB."""
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
   - НЕ создает settings        +--→ to_resolver_settings()      → ResolverSettings
   - передает секции             +--→ to_vault_rollout_policy()   → VaultRolloutPolicySettings
     в субконтейнеры             +--→ to_vault_rollout_thresholds → VaultRolloutThresholds
            |                    +--→ to_vault_db_config()        → SqliteDbConfig
            v                    +--→ to_cache_db_config()        → SqliteDbConfig
   usecases / stages             +--→ to_match_batch_settings()   → MatchBatchSettings
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

**Тесты**:
- ✅ (план) Architecture test: `load_app_config()` остаётся единственным production entrypoint для user-facing config
- ✅ (план) Architecture test: запрет автономной инстанциации `BaseSettings` в `containers.py` и command handlers
- ✅ (план) Architecture test: запрет дублирования projection-функций в command handlers
- ✅ (план) Unit tests: все projection-функции в `projections.py`
- ✅ (план) Unit tests: `ResolveCore` требует `settings: ResolverSettings` (non-optional), не принимает `None`
- ✅ (план) Unit tests: дефолты `ResolverConfig` совпадают с текущими дефолтами `Settings` (regression guard)
- ✅ (план) Integration tests: `sqlite`/`dictionary` параметры проходят через `CLI > ENV > config > defaults`
- ✅ (план) Regression tests: поведение `vault_rollout` runtime не меняется после выноса projections
- ✅ (план) Test: `config_example.yml` содержит все секции (sync с `AppConfig.model_json_schema()`)

**Метрики успеха**:
- Количество автономных loader-path для settings в delivery/runtime = 0
- Количество дублирующих projection-функций в command handlers = 0
- Нет расхождений между дефолтами config-layer и domain runtime fallback

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
| `connector/infra/target/*` | Косвенное | Централизовать сборку `HttpClientSettings` в `projections.py` |
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
| 2026-02-26 | Статус: Принято. Уточнено: `AppConfig(BaseModel)` заменяет `AppSettings`; `ResolverConfig` в config-слое с projection; `SqliteConfig`/`DictionaryConfig` как секции `AppConfig`; централизованные projections в `projections.py`; hidden defaults cleanup; полная инвентаризация settings-моделей; clean break без backward compat |
