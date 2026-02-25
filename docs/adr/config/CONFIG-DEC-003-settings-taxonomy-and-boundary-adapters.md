# CONFIG-DEC-003: Таксономия Settings и унификация конфигурационных границ/адаптеров

> **Статус**: Предложено
> **Дата принятия**: 2026-02-24
> **Решает проблему**: [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После `CONFIG-DEC-001` появился канонический app/CLI путь `load_app_settings(...)`, а после
`CONFIG-DEC-002` (решение принято, реализация отложена) зафиксирован вектор на Pydantic-first
валидацию. При этом в проекте уже существуют параллельные settings-механизмы:

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

---

## 🎯 Решение

Зафиксировать **единый pipeline доставки конфигурации** и **единую каноническую модель приложения**
(`AppSettings`) как обязательный путь для всех user-facing параметров, а также правила для
производных локальных моделей в точках, где меняется смысл конфигурации.

Ключевые правила:

1. **Единый путь загрузки (обязательный)**  
   Все user-facing параметры проходят путь: `CLI/ENV/config/default -> parse/validate -> AppSettings`.
   Вторичных loader-путей в `containers.py`, command handlers и runtime-компонентах быть не должно.

2. **Одна каноническая app-модель**  
   `AppSettings` — единый внутренний контракт приложения (nested sections, immutable/frozen),
   из которого контейнер и слои получают настройки.

3. **`BaseSettings` только на boundary загрузки**  
   `BaseSettings`/источники чтения (`ENV`, `CLI`, `config`) живут в config-layer загрузчика.
   Domain/Delivery/Infra runtime не создают `BaseSettings` автономно.

4. **Контейнер — “глупый” получатель зависимостей**  
   DI-container не является loader'ом конфигурации и не должен самостоятельно инстанцировать
   settings-модели. Он получает `AppSettings` и извлекает из него секции/зависимости.

5. **Производные локальные модели допустимы только при смене смысла**  
   Если конфигурация меняет архитектурную роль (например, превращается в effective DB config,
   transport config или policy input), создаётся отдельная локальная модель через projection/builder.

6. **Domain policy settings не конкурируют с config-layer по дефолтам**  
   Доменные `*Settings` остаются value-object'ами и не содержат скрытых fallback-дефолтов,
   дублирующих/заменяющих дефолты config-layer без явного решения.

7. **Projections/builder'ы централизуются**  
   Преобразования `AppSettings -> domain policy / component config` выполняются в одном месте
   (config/delivery boundary module), а не дублируются в командах.

8. **Invocation intent не входит в `AppSettings`**  
   Параметры, определяющие поведение *конкретного запуска*, а не деплоя, остаются в CLI-opts:
   `--vault-mode`, `--include-*-items`, per-run dataset override и т.п.
   Они не являются deploy-managed параметрами и не должны сохраняться как часть app-контура.

9. **Секретный материал не входит в `AppSettings`**  
   Значения ключей/паролей/токенов остаются секретами.  
   Допустимо хранить **пути** к файлам с секретами/сертификатами/паролями в `AppSettings`,
   но не сами секреты.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые/целевые компоненты**:
- `AppSettings` как **каноническая модель приложения** (nested sections)
  - включает user-facing секции: `api`, `paths`, `observability`, `matching_runtime`,
    `resolver`, `sqlite`, `dictionary`, `vault_rollout`, ...
- `connector/config` projection/builder модуль (имя определяется в реализации)
  - централизованные функции преобразования `AppSettings` в domain policy inputs и component configs

**Изменения в существующих компонентах**:
- `connector/config/app_settings.py`
  - `load_app_settings(...)` собирает все user-facing секции в едином pipeline
  - runtime-секции (`sqlite`, `dictionary`) входят в `AppSettings`, а не создаются отдельно в контейнере
- `connector/delivery/cli/containers.py`
  - удаляется автономная инстанциация settings (`SqliteSettings()`, `DictionaryRuntimeSettings()`)
  - контейнер получает `app_settings` и использует `providers.Callable(lambda s: s.sqlite, s=app_settings)` и аналоги
- `connector/delivery/commands/*`
  - удаляется дублирование ручных mappings (`_rollout_settings(...)`, часть threshold-mappings)
- `connector/domain/transform/resolver/*`
  - согласуется поведение fallback/default с config-layer (убрать hidden defaults или централизовать временно)

### Таксономия моделей (единый путь + разные роли)

1. **Loader model (граница источников)**
   - роль: чтение/merge/валидация `CLI/ENV/config/default`
   - технология: `BaseSettings`/Pydantic settings source chain
   - владелец: `connector/config`

2. **Canonical app model (`AppSettings`)**
   - роль: внутренний типизированный контракт приложения
   - технология: `BaseModel` (frozen)
   - владелец: `connector/config`

3. **Domain policy inputs (`ResolverSettings`, `VaultRolloutPolicySettings`, thresholds)**
   - роль: входы доменных policy/алгоритмов
   - технология: VO/DTO (Pydantic `BaseModel` или dataclass — по задаче)
   - владелец: domain слой

4. **Component-local runtime configs (`SqliteDbConfig`, `HttpClientSettings`)**
   - роль: эффективная конфигурация конкретного компонента/транспорта
   - владелец: infra компонент

### Что не входит в `AppSettings` (и почему)

1. **Invocation intent (CLI-only опции)**  
   Примеры: `--vault-mode`, `--include-*-items`, per-run dataset override.  
   Причина: это *параметры конкретного запуска*, а не деплоя. Их хранение в `AppSettings`
   ломает семантику “deploy-managed config”, усложняет повторяемость и кеширование настроек.

2. **Component-local effective configs**  
   Примеры: `SqliteDbConfig`, `HttpClientSettings`.  
   Причина: это вычисленные “effective” параметры конкретного компонента, не исходные настройки.
   Они порождаются из `AppSettings` через builders/projections и не должны становиться частью
   глобального контракта приложения.

3. **Секретный материал**  
   Примеры: master keyring, токены, пароли.  
   Причина: это секреты, а не настройки.  
   Допустимо хранить **пути к файлам** или **идентификаторы секретов** в `AppSettings`.

4. **DSL `location_ref` env-значения**  
   `location_ref` — это runtime-resolution источника данных (data boundary), а не app config.
   Если нужен перенос, он должен быть оформлен отдельно как boundary механика, а не как
   часть `AppSettings`.

### Когда “меняется смысл” (и нужен projection/builder)

Смена смысла означает, что объект конфигурации перестаёт быть “параметрами приложения, заданными
пользователем” и становится “эффективными параметрами конкретного механизма”.

Projection/builder обязателен, если выполняется хотя бы один признак:

- меняется **владелец ответственности** (config-layer -> domain policy / infra component),
- появляется **вычисление** (`host + port -> base_url`, override chains, normalisation),
- меняется **гранулярность** (один app-section -> несколько локальных объектов),
- меняется **область действия** (общая конфигурация -> config одного соединения/клиента),
- меняются **инварианты потребителя** (декларативные настройки -> effective runtime config).

Примеры:
- `AppSettings.sqlite` -> `SqliteDbConfig` (effective config конкретного DB connection)
- `AppSettings.api` -> `HttpClientSettings` (transport runtime config)
- `AppSettings.vault_rollout` -> `VaultRolloutPolicySettings` + `VaultRolloutThresholds`

Контрпример (projection не обязателен):
- `AppSettings.matching_runtime` передаётся в use case/stage почти 1:1 без смены роли/семантики

### Интерфейсы

```python
# Канонический entrypoint загрузки
def load_app_settings(
    config_path: str | None,
    cli_overrides: dict[str, object],
) -> LoadedAppSettings: ...


class AppSettings(BaseModel):
    api: ApiSettings
    paths: PathsSettings
    observability: ObservabilitySettings
    matching_runtime: MatchingRuntimeSettings
    resolver: ResolverSettings
    sqlite: SqliteSettings
    dictionary: DictionaryRuntimeSettings
    vault_rollout: VaultRolloutSettings


# Централизованные projections/builders (пример API)
def build_vault_rollout_policy_settings(s: AppSettings) -> VaultRolloutPolicySettings: ...
def build_vault_rollout_thresholds(s: AppSettings) -> VaultRolloutThresholds: ...
def build_vault_db_config(sqlite: SqliteSettings) -> SqliteDbConfig: ...
def build_cache_db_config(sqlite: SqliteSettings) -> SqliteDbConfig: ...
def build_http_client_settings(api: ApiSettings, *, transport: object | None = None) -> HttpClientSettings: ...
```

### Поток данных

```
[CLI args]   [ENV vars]   [config.yml]   [defaults]
    \           |             /              /
     \          |            /              /
      +---------+-----------+--------------+
                        |
                        v
        load_app_settings(...)  # parse + validate + diagnostics + source-trace
                        |
                        v
             AppSettings (canonical app model)
                        |
            +-----------+------------+
            |                        |
            v                        v
   DI Container (получатель)   Central projections/builders
            |                        |
            v                        v
     usecases / stages         domain policy inputs / component configs
                                     (SqliteDbConfig, HttpClientSettings, ...)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Даёт один обязательный pipeline доставки конфигурации для всех user-facing параметров
- ✅ Делает `AppSettings` единой канонической моделью приложения вместо конкурирующих entrypoints
- ✅ Устраняет автономную загрузку settings в контейнере и дублирующие mappings в командах
- ✅ Чётко разделяет: loader model / app model / domain policy input / component-local config
- ✅ Поддерживает поэтапную миграцию на Pydantic без массового переписывания доменных/infra моделей
- ✅ Снижает риск drift между дефолтами config-слоя и runtime-поведением

**Недостатки (компромиссы)**:
- ⚠️ Не означает “одна модель для всего”: локальные projections всё равно останутся там, где меняется смысл
- ⚠️ Требует дисциплины и архитектурных тестов, иначе container/commands снова начнут создавать свои loader-пути
- ⚠️ Миграция `AppSettings` в nested canonical model затрагивает `config` и DI wiring одновременно

**Альтернативы, которые отклонили**:
- ❌ **Оставить текущий split и только документировать**: не устраняет hidden defaults, автономную загрузку в контейнере и дублирующие mappings
- ❌ **“Одна модель для всего” (включая доменные/infra локальные конфиги)**: смешивает роли и размывает архитектурные границы
- ❌ **Сразу полная миграция всех settings на единый Pydantic loader без промежуточных guardrails**: высокий риск и конфликт с параллельными миграциями

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/config/app_settings.py` | `AppSettings` становится canonical nested model; `load_app_settings(...)` собирает все user-facing секции |
| `connector/delivery/cli/containers.py` | Удалить автономную инстанциацию settings; извлекать секции из `app_settings` |
| `connector/config/*` (новый projection/builder модуль) | Централизовать semantic projections (`vault rollout`, `http client settings`, и т.п.) |
| `connector/delivery/commands/enrich.py` | Удалить локальный `_rollout_settings(...)`, использовать projection |
| `connector/delivery/commands/import_plan.py` | Удалить локальный `_rollout_settings(...)`, использовать projection |
| `connector/delivery/commands/import_apply.py` | Перевести `_rollout_settings(...)` / `_rollout_thresholds(...)` на projection |
| `connector/domain/transform/resolver/resolve_core.py` | Убрать/изолировать скрытые fallback-дефолты |
| `tests/architecture/config/test_settings_boundaries.py` | Добавить guardrails на единый pipeline и запрет автономного loader-path |

### План перехода (фиксируем в ADR)

1. **Миграция на Pydantic (CONFIG-DEC-002) — обязательный первый шаг**  
   - `Settings` -> Pydantic `BaseSettings`  
   - `AppSettings` -> Pydantic `BaseModel`  
   - сохранение `LoadedAppSettings` (warnings/source_trace/error-contract)

2. **Включение runtime секций в `AppSettings`**  
   - `sqlite` и `dictionary` становятся секциями canonical `AppSettings`  
   - удаляется автономная инстанциация `SqliteSettings()` / `DictionaryRuntimeSettings()` в контейнере

3. **Централизация projections/builders**  
   - вынос `vault_rollout` mapping из command handlers  
   - централизованный builder для `HttpClientSettings`  
   - единые `build_*_db_config(...)` как canonical projections

4. **Resolver fallback cleanup**  
   - явный путь доставки `ResolverSettings`  
   - удаление hidden fallback из `ResolveCore`

5. **Guardrails / тесты**  
   - запреты автономных loader-path  
   - запреты дублирующих projections  
   - синхронизация `config_example.yml` с schema

### Ключевые методы

- `load_app_settings(...)` — единственный production entrypoint для user-facing app settings
- `build_vault_rollout_policy_settings(...)` (планируемый projection) — единая точка mapping
- `build_vault_rollout_thresholds(...)` (планируемый projection) — единая точка threshold-mapping
- `build_*_db_config(...)` / `build_http_client_settings(...)` — локальные effective-config builders

### Инварианты

1. **Все user-facing настройки проходят через единый pipeline `load_app_settings(...)`.**
2. **`BaseSettings` не инстанцируется в контейнере, командах, use cases и domain runtime.**
3. **`AppSettings` — канонический внутренний контракт приложения для доставки настроек.**
4. **Projections/builders создаются только при смене смысла конфигурации.**
5. **Domain policy settings не содержат конкурирующих hidden defaults без явного решения/документации.**
6. **Component-local configs не становятся вторым глобальным settings-entrypoint.**
7. **Секретный материал не хранится в `AppSettings`; допустимы только пути/идентификаторы.**

---

## 🧪 Валидация решения

**Тесты**:
- ✅ (план) Architecture test: `load_app_settings(...)` остаётся единственным production entrypoint для user-facing config
- ✅ (план) Architecture test: запрет автономной инстанциации `BaseSettings` в `delivery/cli/containers.py` и command handlers
- ✅ (план) Architecture test: запрет дублирования `VaultRolloutSettings -> VaultRolloutPolicySettings` mapping в command handlers
- ✅ (план) Unit tests: projections/builders для rollout policy/thresholds и `HttpClientSettings`
- ✅ (план) Unit/integration tests: resolver runtime использует явно доставленный `ResolverSettings`, а не скрытый fallback
- ✅ (план) Integration tests: `sqlite`/`dictionary` user-facing параметры проходят через тот же `CLI > ENV > config > defaults` pipeline
- ✅ (план) Regression tests: поведение CLI `vault_rollout` и target HTTP runtime не меняется после выноса projections

**Проверка в production**:
1. Прогнать команды `enrich`, `import-plan`, `import-apply` с одинаковым `vault_rollout` config
2. Сравнить runtime context/report до и после выноса projections
3. Проверить, что `sqlite`/`dictionary` runtime параметры отражают `CLI/ENV/config` overrides через `load_app_settings(...)`
4. Проверить, что resolver pending-параметры берутся из `AppSettings.resolver` по wiring path

**Метрики успеха**:
- Метрика 1: Количество автономных loader-path для settings в delivery/runtime = 0
- Метрика 2: Количество дублирующих rollout projection-функций в command handlers = 0
- Метрика 3: Нет расхождений между дефолтами config-слоя и resolver runtime fallback (fallback либо удалён, либо централизован)

---

## 📐 Диаграммы

**UML диаграммы** (если созданы):
- Не создавались на этапе фиксации решения

**Инфографика: единый путь доставки конфигурации (целевое состояние)**:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER-FACING CONFIG INPUTS                           │
│                    CLI args | ENV vars | config.yml | defaults             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  CONFIG LAYER: load_app_settings(...)                                      │
│  - merge priority                                                          │
│  - parse / validate                                                        │
│  - diagnostics / warnings / source_trace                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  CANONICAL APP MODEL: AppSettings (nested, immutable)                      │
│  api | paths | observability | matching_runtime | resolver | sqlite | ...  │
└─────────────────────────────────────────────────────────────────────────────┘
                     │                           │
                     │                           │ (только при смене смысла)
                     ▼                           ▼
┌───────────────────────────────┐   ┌─────────────────────────────────────────┐
│ DI Container (consumer only)  │   │ Central projections / builders          │
│ - НЕ читает ENV/config        │   │ - AppSettings -> policy inputs          │
│ - НЕ создает BaseSettings     │   │ - AppSettings -> component configs      │
└───────────────────────────────┘   └─────────────────────────────────────────┘
                     │                           │
                     └──────────────┬────────────┘
                                    ▼
                   use cases / stages / infra components runtime
```

**Инфографика: когда нужен projection/builder**:

```text
AppSettings section ──► Можно передать как есть?
                        │
                        ├─ Да ─► Передаём напрямую (semantics unchanged)
                        │       Пример: matching_runtime -> use case
                        │
                        └─ Нет ─► Почему?
                                 - changed owner?
                                 - computed/effective values?
                                 - split into multiple inputs?
                                 - consumer-specific invariants?
                                 │
                                 └─► Делаем projection / builder
                                     Примеры:
                                     api -> HttpClientSettings
                                     sqlite -> SqliteDbConfig
                                     vault_rollout -> policy + thresholds
```

**Примеры использования**:

```python
# Bootstrap / composition root (целевое состояние)
loaded = load_app_settings(config_path=config_path, cli_overrides=cli_overrides)
container = AppContainer(app_settings=providers.Object(loaded.app_settings))

# Container reads sections from canonical model (не создает BaseSettings сам)
# _sqlite_cfg = providers.Callable(lambda s: s.sqlite, s=app_settings)

# Command/runtime use centralized projections only where semantics changes
rollout_policy = build_vault_rollout_policy_settings(ctx.app_settings)
thresholds = build_vault_rollout_thresholds(ctx.app_settings)
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Решение фиксирует архитектурные границы и pipeline доставки, но не заменяет `CONFIG-DEC-002`
  (полную Pydantic-модернизацию settings-слоя)
- На переходном этапе возможен hybrid-state, где часть секций ещё не вошла в canonical nested `AppSettings`
- Названия projection/builder модулей могут уточняться в реализации без изменения сути решения
- Hot reload параметров **не закладывается** в текущем решении (отдельный scope/schedule)

**Риски**:
- ⚠️ Риск 1: Одновременные изменения в pipeline/DI миграции могут конфликтовать с переходом на canonical nested `AppSettings`
  → Митигация: выполнять миграцию по секциям, начиная с `sqlite`/`dictionary`, с архитектурными тестами на каждом шаге
- ⚠️ Риск 2: Удаление resolver fallback может затронуть legacy/tests, где `ResolveCore` создаётся без settings
  → Митигация: сначала ввести явный путь доставки `ResolverSettings`, затем сужать legacy API
- ⚠️ Риск 3: Перегиб в “projection everywhere” создаст лишнюю бюрократию
  → Митигация: projection разрешён только при подтверждённой смене смысла (по критериям из этого ADR)
- ⚠️ Риск 4: Попытка добавить hot reload раньше времени усложнит DI и runtime
  → Митигация: рассматривать hot reload отдельно как schedule/feature, после стабилизации pipeline

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/config` | Прямое | Реализовать единый pipeline + canonical `AppSettings` + projections policy |
| `connector/delivery/cli/containers.py` | Прямое | Перестать создавать settings-модели автономно; читать секции из `app_settings` |
| `connector/delivery/commands/*` | Прямое | Удалить дублирующие rollout mappings, использовать централизованные projections |
| `connector/domain/transform/resolver/*` | Прямое | Согласовать fallback/default поведение с config-layer |
| `connector/infra/target/*` | Косвенное | Централизовать сборку `HttpClientSettings` при необходимости |
| `tests/architecture/config/*` | Прямое | Добавить guardrails на единый pipeline и запрет автономных loader-path |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md)
- ✅ [CONFIG-DEC-003](./CONFIG-DEC-003-settings-taxonomy-and-boundary-adapters.md)
- ✅ [ADR Index](../INDEX.md) (раздел Config)

---

## 🔗 Связанные документы

- [CONFIG-PROBLEM-003](./CONFIG-PROBLEM-003-settings-fragmentation-and-runtime-default-drift.md) - решаемая проблема
- [CONFIG-DEC-001](./CONFIG-DEC-001-modular-settings-and-slice-wiring.md) - канонический slice-based wiring
- [CONFIG-DEC-002](./CONFIG-DEC-002-pydantic-settings-migration.md) - стратегический вектор Pydantic migration
- [TRANSFORM-DEC-004](../transform/TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) - typed capability context для стадий
- [DELIVERY-DEC-006](../delivery/DELIVERY-DEC-006-app-container-composition-root-integration.md) - `AppContainer` как composition root

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Решение предложено по итогам архитектурного обзора settings/config границ |
| 2026-02-24 | Уточнено после обсуждения: единый pipeline + canonical `AppSettings`; projections только при смене смысла |
