# TRANSFORM-DEC-001: Справочная подсистема enrich (Polars v1, migration-ready для v2: Polars+DuckDB+Parquet)

> **Статус**: Предложено / Отложена
> **Дата принятия**: 2026-02-19
> **Решает проблему**: [TRANSFORM-PROBLEM-001](./TRANSFORM-PROBLEM-001-enrich-dictionary-runtime-gap.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

В domain уже есть `DictionaryProviderPort`, а в enrich runtime зарегистрирован провайдер
`dictionary.by_key`. Проблема в отсутствии боевой реализации.

Текущая продуктовая цель v1:
- словари небольшие (ориентир 100-200 строк);
- обработка целиком in-memory;
- минимальный overhead на запуск и сопровождение;
- обязательная архитектурная изоляция для безболезненной миграции на v2
  (`Polars + DuckDB + Parquet`).

---

## 🎯 Решение

Принять двухфазную стратегию с фиксированным v1:

1. **v1 runtime**: `Polars + CSV`.
2. `DictionaryProviderPort` остается стабильным доменным контрактом.
3. Enrich использует только порт и не зависит от Polars/DuckDB.
4. **DuckDB не используется в v1**, но границы фиксируются так, чтобы в v2 добавить DuckDB
   как storage/query слой при сохранении Polars как execution/transformation слоя.
5. YAML/DSL используется как control plane (описание схемы/ключей/правил), данные словаря
   остаются в CSV-файлах в v1.

---

## 🏗️ Архитектурное решение

### Карта ответственности (строго по слоям)

- **Domain (`connector/domain/...`)**:
  - Обязан: определять только контракт порта (`DictionaryProviderPort`) и бизнес-использование.
  - Запрещено: импортировать Polars, DuckDB, file/storage детали.
- **Infra v1 (`connector/infra/dictionaries/...`)**:
  - Обязан: загрузка CSV, хранение in-memory DataFrame, lookup/contains/canonicalize.
  - Запрещено: встраивать бизнес-решения enrich и stage-оркестрацию.
- **Infra v2 (future)**:
  - Обязан: добавить DuckDB storage/query слой и хранение словарей в Parquet/DuckDB.
  - Обязан: сохранить Polars как execution слой для in-memory логики.
  - Запрещено: менять domain API и enrich DSL контракт.
- **Delivery/Wiring**:
  - Обязан: выбрать backend реализации и передать в `TransformProviderDeps`.
  - Запрещено: реализовывать lookup-логику внутри контейнера/wiring.

### DI-стратегия (forward adoption)

`DictionaryContainer` — `DeclarativeContainer`, который монтируется как субконтейнер в
`AppContainer` через `providers.Container(DictionaryContainer, ...)`.

Файл `connector/delivery/cli/dictionaries_container.py` содержит только описание
`DictionaryContainer` — он **не является автономным Composition Root**.
Единственный CR приложения — `AppContainer` в `connector/delivery/cli/containers.py`.

Границы:
1. DI-контейнер создается и используется только на уровне wiring (`connector/delivery/cli/`).
2. Domain/use-case/stage-код не получает container как зависимость.
3. Внедрение зависимостей остается constructor-based через контракты (`DictionaryProviderPort`).
4. `DictionaryContainer` монтируется в `AppContainer` через `providers.Container(...)`.
5. `PipelineContainer.dictionaries` (уже существует как `providers.Object(None)`) переопределяется
   в `_init_container_for_requirements()` реальным провайдером при `requires_dictionaries=True`.

Lifecycle провайдеров (v1):
- `DictionaryDslRuntimeBundle` — `Singleton` (DSL parsing, нет IO).
- `CsvDictionaryLoader` — `Singleton` (stateless).
- `PolarsDictionaryBackend` — `Resource` (eager CSV load при `init_resources()` → fail-fast).
- `PolarsDictionaryProvider` адаптер — `Singleton` (поверх `Resource` backend).

Смысл `Resource` для backend: `init_resources()` выполняет eager CSV load; любой `DslLoadError`
(файл не найден, fingerprint mismatch, дубли ключей) всплывает сразу — AppContainer завершает
run fail-fast. Teardown не нужен (read-only in-memory).

Переход v1 -> v2:
- container API для потребителей не меняется;
- в DI-графе меняются только infra-провайдеры backend/storage;
- wiring остальных слоев остается неизменным.

### Карта ответственности (модуль/класс/метод)

- **Модуль `connector/domain/dictionary_dsl/specs.py`**:
  - Обязан: валидировать конфигурацию словаря (имя, путь CSV, ключ, колонки);
    whitelist-проверка `normalized_key.ops` через `@field_validator` (domain-правило).
  - Запрещено: читать данные, выполнять lookup, импортировать Polars/DuckDB/infra.
- **Модуль `connector/infra/dictionaries/dsl_runtime.py`**:
  - Обязан: принять `dict[str, DictionarySpec]` (уже прошедший Pydantic-валидацию)
    и построить `DictionaryDslRuntimeBundle`; резолюция имён ops через `OperationRegistry`
    (`op_name → Operation`) — infra-шаг связывания, не бизнес-правило.
  - Запрещено: применять whitelist-правила (это specs.py), выполнять IO (читать CSV),
    принимать решения о том, какие словари включить.
- **Модуль `connector/infra/dictionaries/loader_csv.py`**:
  - Обязан: читать CSV и загружать данные в backend (`load_into(backend)`).
  - Запрещено: бизнес-валидация enrich-правил, whitelist-проверки ops.
- **Класс `connector/infra/dictionaries/telemetry.py` → `DictionaryTelemetry`**:
  - Обязан: владеть runtime-счётчиками (`lookup_total/hit/miss/error`) и logging через
    structlog; оба аспекта когезивны — каждое изменение счётчика неотделимо от log-события.
  - Запрещено: содержать lookup-логику, знать про pipeline-оркестрацию.
  - Trade-off v1: logging и counters в одном классе; при росте ответственности — разделить
    на `DictionaryRuntimeCounters` (dataclass) + stateless logging helpers.
- **Класс `PolarsDictionaryProvider`**:
  - Обязан: реализовать `DictionaryProviderPort`; делегировать в backend; обновлять телеметрию.
  - Запрещено: знать про pipeline stage/diagnostics orchestration.
- **Метод `lookup()`**:
  - Обязан: только поиск по словарю с projection/limit.
  - Запрещено: side effects (запись в файлы/изменение source snapshots).

### Компоненты v1

**Новые модули**:
- `connector/domain/dictionary_dsl/specs.py`
- `connector/domain/dictionary_dsl/loader.py`
- `connector/domain/dictionary_dsl/__init__.py`
- `connector/infra/dictionaries/dsl_runtime.py`
- `connector/infra/dictionaries/loader_csv.py`
- `connector/infra/dictionaries/backends/polars_backend.py`
- `connector/infra/dictionaries/provider.py`
- `connector/infra/dictionaries/telemetry.py`
- `connector/infra/dictionaries/versioning.py`

`connector/infra/dictionaries/cache.py` исключен из целевого дизайна v1: отдельный слой
вторичного кэширования не нужен для профиля 100-200 строк и дублирует ответственность
`polars_backend.py`.

**Изменения в существующих компонентах**:
- `connector/domain/ports/transform/dictionaries.py`: закрепить стабильный API lookup.
- `connector/domain/transform/providers/registry.py`: пробросить lookup-аргументы (`fields`, `limit`).
- `connector/datasets/*/spec.py`: передавать `dictionaries` в `TransformProviderDeps`.

### Контракты

```python
class DictionaryProviderPort(Protocol):
    def lookup(
        self,
        dict_name: str,
        key: str,
        at: Any | None = None,
        fields: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def contains(self, dict_name: str, value: str, at: Any | None = None) -> bool: ...

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        at: Any | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
```

```python
class DictionaryRegistryItemSpec(DslBaseModel):
    spec: str
    enabled: bool = True


class DictionaryRegistrySpec(DslBaseModel):
    version: Literal[1]
    items: dict[str, DictionaryRegistryItemSpec]


class DictionarySourceCsvSpec(DslBaseModel):
    delimiter: str = ","
    has_header: bool = True
    encoding: str = "utf-8"


class DictionarySourceSpec(DslBaseModel):
    format: Literal["csv"]
    location: str
    csv: DictionarySourceCsvSpec = Field(default_factory=DictionarySourceCsvSpec)


class DictionaryNormalizedKeySpec(DslBaseModel):
    ops: list[OperationCall] = Field(default_factory=list)


class DictionarySchemaSpec(DslBaseModel):
    key_column: str
    value_columns: list[str]
    normalized_key: DictionaryNormalizedKeySpec | None = None


class DictionaryLookupSpec(DslBaseModel):
    allow_duplicates: bool = False


class DictionarySpec(DslBaseModel):
    dictionary: str
    source: DictionarySourceSpec
    schema: DictionarySchemaSpec
    lookup: DictionaryLookupSpec = Field(default_factory=DictionaryLookupSpec)
```

В ADR фиксируется **одна каноническая модель `DictionarySpec`** (Pydantic DSL boundary).
Отдельная публичная dataclass-модель для той же сущности не вводится.

### Контракт args провайдера `dictionary.by_key` (v1)

`provider: dictionary.by_key` поддерживает только:
- обязательный `dict_name: str`;
- опциональный `at: Any`;
- опциональный `fields: list[str] | tuple[str, ...]`;
- опциональный `limit: int` (`> 0`).

Политика валидации:
- unknown args отклоняются на compile/load этапе (`DslLoadError`);
- `limit <= 0` отклоняется на compile/load этапе (`DslLoadError`);
- runtime provider не расширяет контракт ad-hoc аргументами.

### Контракт `exists`/`canonicalize` провайдеров (v1)

`provider: dictionary.exists_by_key` (exists-channel) поддерживает:
- обязательный `dict_name: str`;
- опциональный `at: Any`;
- опциональный `fields: list[str] | tuple[str, ...]`.

Семантика `dictionary.exists_by_key`:
- реализуется через `lookup(..., limit=1)`;
- возвращает `row | None` (не `bool`), чтобы быть совместимым с enrich exists flow.
- backend может применять hot-path оптимизацию через in-memory key-set индекс
  (`contains` за `O(1)`) и выполнять `lookup(..., limit=1)` только при hit.

`provider: dictionary.canonicalize` (lookup-channel) поддерживает:
- обязательный `dict_name: str`;
- опциональный `at: Any`;
- опциональный `limit: int` (`> 0`).

Важно:
- `DictionaryProviderPort.contains()` не маппится напрямую в enrich DSL `exists`,
  потому что exists-path enrich ожидает `row | None`, а не `bool`.
- реализация backend для `contains`/`exists` в v1 может использовать set-based индекс по
  normalized key вместо линейного `DataFrame.filter(...).height > 0` скана.

### Контракт `normalized_key.ops` (v1)

Источник операций:
- используется тот же общий DSL registry, что и в transform DSL
  (`connector/domain/dsl/registry.py`, `register_core_ops`);
- отдельный registry для dictionary runtime в v1 не вводится.

Разрешённое подмножество для `normalized_key.ops` (v1):
- `trim`
- `lower`
- `upper`
- `to_string`
- `regex_replace`

Правила применения:
- нормализация применяется к `schema.key_column` при загрузке CSV (формирование normalized key индекса);
- та же цепочка ops применяется к входному lookup key при `lookup`/`canonicalize`/`contains`;
- при отсутствии `normalized_key` используется raw-ключ на обеих сторонах.

Это обязательная симметрия: одинаковые ops на load-path и lookup-path, иначе поиск считается
некорректной конфигурацией runtime.

### CSV edge cases (v1)

Encoding/BOM:
- `source.csv.encoding` default: `utf-8`;
- loader обязан поддерживать BOM stripping (`utf-8-sig` поведение) без изменения полезных данных.

Пустой CSV:
- CSV с header и 0 data rows считается валидным словарём;
- runtime продолжает запуск, словарь имеет `row_count=0`;
- фиксируется предупреждение (`DICT_SOURCE_EMPTY`, severity `WARNING`) в diagnostics/report context.

Дубли ключей:
- при `lookup.allow_duplicates=false` любые дубли по `key_column` в CSV — fail-fast:
  `DslLoadError(code=\"DICT_SCHEMA_INVALID\")`;
- при `lookup.allow_duplicates=true` дубли допустимы, lookup возвращает все совпадения
  (с учётом `fields`/`limit`).

### Поток данных v1

```
CSV snapshot
    ↓
CsvDictionaryLoader -> Polars DataFrame
    ↓
PolarsDictionaryProvider (in-memory index/lookup)
    ↓
DictionaryProviderPort.lookup(...)
    ↓
enricher (dictionary.by_key)
```

### Контур миграции v1 -> v2 (без боли)

1. `DictionaryProviderPort` не меняется.
2. DSL правило `dictionary.by_key` не меняется.
3. Меняется только infra/backend + wiring:
   - v1: `CsvDictionaryLoader -> PolarsDictionaryProvider`;
   - v2: `Parquet/DuckDB storage layer -> Polars execution layer -> DictionaryProviderPort`.
4. Manifest расширяется вперед-совместимо:
   - v1: `source.format=csv`;
   - v2: добавляются `parquet/duckdb` поля без ломки существующих CSV-словарей.

### DSL и YAML (control plane)

Назначение Dictionary DSL в v1:
- декларативная регистрация словаря;
- описание схемы lookup (key/value/normalization);
- валидация конфигурации до runtime.

Dictionary DSL **не** используется как канал CRUD-операций над строками словаря.
Данные словаря живут в CSV snapshot-файлах (в v2 — Parquet/DuckDB).

Пример 1: registry-вход в `datasets/registry.yml`

```yaml
dictionaries:
  version: 1
  items:
    organizations:
      spec: dictionaries/organizations.dictionary.yaml
      enabled: true
```

Пример 2: spec одного словаря `datasets/dictionaries/organizations.dictionary.yaml`

```yaml
dictionary: organizations
source:
  format: csv
  location: dictionaries/organizations.csv
  csv:
    delimiter: ","
    has_header: true
    encoding: utf-8
schema:
  key_column: code
  value_columns: [ouid, name]
  normalized_key:
    ops:
      - op: trim
      - op: lower
lookup:
  allow_duplicates: false
```

### Pydantic-forward adoption (граница данных)

Pydantic обязателен на входных границах Dictionary DSL:
- `DictionaryRegistrySpec` (секция `dictionaries` в `registry.yml`);
- `DictionarySpec` (файл `*.dictionary.yaml`);
- `DictionaryManifestSpec` (файл `datasets/dictionaries/manifest.yml`);
- вложенные модели `source/schema/lookup`.

Инварианты, которые покрывает Pydantic:
1. `DictionaryRegistrySpec.version` фиксирован как `1`.
2. `DictionaryRegistrySpec.items` содержит `dict_name -> DictionaryRegistryItemSpec`.
3. `dictionary` не пустой и уникальный в рамках registry.
4. `source.format=csv` в v1, `source.location` обязателен.
5. `key_column` не входит в конфликт с `value_columns`.
6. `value_columns` не пустой.
7. `normalized_key.ops` валидируется как список `OperationCall`.
8. `normalized_key.ops[].op` ограничивается whitelist-подмножеством через `@field_validator`
   в `DictionaryNormalizedKeySpec` (domain-правило, не infra):

```python
DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST: frozenset[str] = frozenset({
    "trim", "lower", "upper", "to_string", "regex_replace",
})

class DictionaryNormalizedKeySpec(DslBaseModel):
    ops: list[OperationCall] = Field(default_factory=list)

    @field_validator("ops", mode="after")
    @classmethod
    def _validate_ops_whitelist(cls, ops: list[OperationCall]) -> list[OperationCall]:
        invalid = {op.op for op in ops} - DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST
        if invalid:
            raise ValueError(
                f"ops not allowed in normalized_key: {sorted(invalid)}. "
                f"Allowed: {sorted(DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST)}"
            )
        return ops
```

9. `source.csv.encoding` задан и по умолчанию равен `utf-8`.

Все ошибки загрузки/валидации оборачиваются в `DslLoadError` с кодами `DICT_DSL_*`
(стандартный паттерн: `loader.py` оборачивает `ValidationError → DslLoadError`).
В runtime lookup-path повторная ручная валидация не выполняется.

### Что уже есть в проекте и что добавляем

Уже есть:
- общий DSL foundation: `DslBaseModel`, `DslLoadError`, loader utils;
- консистентные паттерны DSL загрузки в `transform_dsl`, `cache_dsl`, `target_dsl`;
- lookup-интеграция в enrich через `dictionary.by_key` и `DictionaryProviderPort`.

Добавить:
- новый модуль `connector/domain/dictionary_dsl/`:
  - `specs.py` (Pydantic модели);
  - `loader.py` (загрузка registry + dataset spec);
  - `__init__.py` (public API).
- runtime bundle в infra:
  - `connector/infra/dictionaries/dsl_runtime.py` (по аналогии с `cache/dsl_runtime.py`);
  - `connector/infra/dictionaries/loader_csv.py`;
  - `connector/infra/dictionaries/backends/polars_backend.py`.
  - `connector/infra/dictionaries/provider.py`;
  - `connector/infra/dictionaries/telemetry.py`;
  - `connector/infra/dictionaries/versioning.py`.
- локальный DI в composition root:
  - `connector/delivery/cli/dictionaries_container.py` (новый локальный container);
  - загрузка dictionary DSL runtime (`DictionaryDslRuntimeBundle`, Singleton);
  - сборка `DictionaryProviderPort` реализации (Singleton);
  - наружу выходит только `DictionaryProviderPort` — передаётся в
    `build_pipeline_context()` (`containers.py`) через параметр `dictionaries=`.
- runtime settings для dictionary telemetry:
  - `connector/config/app_settings.py` (`DictionaryRuntimeSettings` как отдельная `BaseSettings`).

### Поток данных: DSL -> Dictionary runtime -> Enrich

1. Прочитать `datasets/registry.yml` и выделить секцию `dictionaries`.
2. Провалидировать как `DictionaryRegistrySpec` (Pydantic).
3. Для каждого enabled словаря загрузить `*.dictionary.yaml`.
4. Провалидировать как `DictionarySpec` (Pydantic).
5. Прочитать `datasets/dictionaries/manifest.yml` и провалидировать как `DictionaryManifestSpec`.
6. Построить runtime bundle (`DictionaryDslRuntimeBundle`: `dict_name -> compiled config`).
7. Загрузить CSV snapshots в Polars backend и сверить `content_sha256` + `schema_hash` по manifest
   (eager default; optional lazy per dictionary).
8. Собрать `DictionaryProviderPort` адаптер.
9. Передать через `dictionaries=` в `build_pipeline_context()` (`containers.py`);
   функция пробрасывает его в `dataset_spec.build_enrich_deps(dictionaries=...)`.
10. Enrich `dictionary.by_key` использует только порт.

### Порядок инициализации container'ов (v1)

Инициализация выполняется в `_init_container_for_requirements()` — единственная точка
условного lifecycle-управления в `AppContainer`.

```python
# connector/delivery/cli/containers.py (фрагмент)

class AppContainer(containers.DeclarativeContainer):
    ...
    _dictionary_settings = providers.Callable(lambda s: s.dictionary, s=app_settings)

    dictionary = providers.Container(
        DictionaryContainer,
        settings=_dictionary_settings,
    )

    pipeline = providers.Container(
        PipelineContainer,
        ...
        # dictionaries=providers.Object(None) — уже есть в PipelineContainer
    )


def _init_container_for_requirements(container: AppContainer, req: Requirements) -> None:
    ...
    if req.requires_dictionaries:
        # Resource: eager CSV load → DslLoadError если broken → fail-fast
        container.dictionary.backend.init()
        # PipelineContainer.dictionaries (providers.Object(None)) → реальный провайдер
        container.pipeline.dictionaries.override(container.dictionary.provider)
    # Если requires_dictionaries=False: PipelineContainer.dictionaries остаётся None
```

Порядок:
1. `AppContainer` создаётся в entry point (CLI-команда / `run_with_report()`).
2. `app_settings` пробрасывается через `override()`.
3. `_init_container_for_requirements()` проверяет `req.requires_dictionaries`.
4. При `requires_dictionaries=True`:
   - `container.dictionary.backend.init()` → eager CSV load (fail-fast при ошибке).
   - `container.pipeline.dictionaries.override(container.dictionary.provider)`.
5. При `requires_dictionaries=False`: словарный runtime не создаётся, `dictionaries=None`.
6. Любая ошибка инициализации dictionary runtime (DSL/spec/manifest/CSV/fingerprint)
   приводит к fail-fast завершению всего run (без silent fallback).
7. `container.shutdown_resources()` вызывается в `finally` — `DictionaryContainer.backend`
   teardown не выполняет IO (read-only in-memory), завершается без ошибок.

### Graceful degradation при отсутствии словарей (v1)

- если секция `dictionaries` отсутствует в `datasets/registry.yml`, dictionary runtime не
  собирается и в `TransformProviderDeps` передается `dictionaries=None`;
- в таком режиме любые вызовы `dictionary.*` провайдеров считаются provider misconfiguration
  и маппятся в `ENRICH_PROVIDER_ERROR`;
- если секция `dictionaries` присутствует, но `items: {}` (пустой набор словарей), это валидная
  конфигурация runtime с `0` словарей;
- для пустого runtime lookup/canonicalize трактуются как miss и маппятся в
  `ENRICH_NO_CANDIDATES`.

### Observability и Diagnostics для Dictionary слоя

Dictionary слой использует существующие контуры report/diagnostics, но с отдельной зоной
ответственности:

1. **Report**:
   - row-level item'ы не добавляются из dictionary runtime;
   - агрегированные метрики пишутся в `report.context["dictionary"]`;
   - per-dictionary breakdown пишется в `report.context["dictionary"]["dictionaries_detail"]`.
2. **Diagnostics catalog**:
   - загрузка/инициализация dictionary DSL и runtime регистрируется новыми `DICT_*` кодами;
   - row-level lookup ошибки остаются в `ENRICH_*` (через текущий enrich flow).
3. **Logging**:
   - в новом dictionary-контуре используется `structlog`;
   - legacy `logging` не мигрируется массово в рамках этой фичи.

Рекомендованные `DICT_*` коды (core catalog):
- `DICT_DSL_REGISTRY_INVALID` -> `SystemErrorCode.DATA_INVALID`
- `DICT_DSL_SPEC_INVALID` -> `SystemErrorCode.DATA_INVALID`
- `DICT_SOURCE_READ_FAILED` -> `SystemErrorCode.IO_ERROR`
- `DICT_SOURCE_MANIFEST_MISSING` -> `SystemErrorCode.DATA_INVALID`
- `DICT_SOURCE_MANIFEST_INVALID` -> `SystemErrorCode.DATA_INVALID`
- `DICT_SOURCE_EMPTY` -> `SystemErrorCode.DATA_INVALID` (severity `WARNING`)
- `DICT_SOURCE_FINGERPRINT_MISMATCH` -> `SystemErrorCode.DATA_INVALID`
- `DICT_SCHEMA_INVALID` -> `SystemErrorCode.DATA_INVALID`
- `DICT_RUNTIME_INIT_FAILED` -> `SystemErrorCode.INTERNAL_ERROR`

Политика размещения diagnostics-кодов:
- v1: `DICT_*` регистрируются только в `connector/domain/diagnostics/core_catalog.py`;
- отдельный dictionary-catalog модуль не вводится в v1;
- выделение в отдельный модуль допускается только при росте таксономии (например, >20
  dictionary-специфичных кодов) или при plugin-доставке layer-catalog.

Row-level mapping для dictionary provider в enrich (`ENRICH_*`):
- lookup miss (ключ не найден) -> `ENRICH_NO_CANDIDATES`;
- lookup error (исключение backend/provider) -> `ENRICH_PROVIDER_ERROR`;
- `deps.dictionaries is None` (секция `dictionaries` отсутствует в `registry.yml`) ->
  `ENRICH_PROVIDER_ERROR`;
- `dict_name` не зарегистрирован в непустом runtime -> `ENRICH_PROVIDER_ERROR`;
- для runtime с `items: {}` (0 словарей) любой `dict_name` трактуется как miss ->
  `ENRICH_NO_CANDIDATES`.

Это правило одинаково для `dictionary.by_key`, `dictionary.canonicalize` и
`dictionary.exists_by_key` в контексте enrich-операций.

Маленький пример: агрегаты dictionary runtime в report context

```python
report.set_context(
    "dictionary",
    {
        "backend": "polars",
        "dictionaries_loaded": 3,
        "rows_loaded_total": 128,
        "lookup_total": 420,
        "lookup_hit": 398,
        "lookup_miss": 20,
        "lookup_error": 2,
        "dictionaries_detail": {
            "organizations": {"rows": 128, "lookup_hit": 300, "lookup_miss": 10, "lookup_error": 1},
            "departments": {"rows": 45, "lookup_hit": 98, "lookup_miss": 10, "lookup_error": 1},
        },
        "load_duration_ms": 34,
    },
)
```

Маленький пример: mapping загрузочной ошибки в diagnostics

```python
raise DslLoadError(
    code="DICT_DSL_SPEC_INVALID",
    message="Invalid dictionary spec",
    details={"dict_name": "organizations", "path": "datasets/dictionaries/organizations.dictionary.yaml"},
)
```

Маленький пример: structlog-событие dictionary runtime

```python
log.info(
    "dictionary_runtime_loaded",
    component="dictionary",
    backend="polars",
    dataset=dataset,
    dictionaries_loaded=len(runtime.specs),
)
```

Лог-уровни и шум:
- `INFO`: startup/load summary, lifecycle события;
- `WARNING`: recoverable аномалии конфигурации/данных;
- `ERROR`: runtime init/lookup failures;
- `DEBUG`: hit/miss lookup-события только с sampling.

### Operational policy (v1) и фундамент для v2

По операционным решениям принимаем:

1. **Sampling policy для DEBUG lookup**:
   - `ERROR/WARNING`: 100% логов;
   - `DEBUG miss`: 10%;
   - `DEBUG hit`: 1%;
   - ключи не логируются в plaintext, только `key_fingerprint`.
2. **Reload strategy**:
   - v1: `startup-only` (словари загружаются один раз на запуск команды);
   - обновления CSV подхватываются только в следующем run.
3. **Load strategy (v1)**:
   - default: eager startup-load всех enabled словарей;
   - опция: lazy-load per dictionary (загрузка CSV при первом lookup/canonicalize к конкретному словарю);
   - в lazy-mode словари, к которым не было обращения, не грузятся и не валидируются в рамках run;
   - ошибки загрузки/manifest/fingerprint в lazy-mode поднимаются в момент первого обращения к словарю;
   - lazy-load режим не отменяет startup-only reload policy.
4. **Versioning contract (v1/v2 единый)**:
   - единый контракт версии сохраняется в report/log/diagnostics;
   - меняется только стратегия вычисления fingerprint по формату источника.

### Concurrency model

v1:
- модель исполнения — single-threaded runtime для dictionary layer;
- `Polars`-таблицы словарей используются как read-only;
- telemetry counters в v1 не декларируются как thread-safe;
- Singleton lifecycle не является гарантией безопасного конкурентного доступа.

v2:
- при переходе к конкурентному выполнению (параллельные pipelines / workers) требуется явная
  стратегия thread-safety для telemetry counters (`threading.Lock`/atomic counters) и
  документированная модель доступа к runtime/backend.

Единый контракт `DictionaryVersionInfo`:
- `dict_name`
- `version_id`
- `schema_hash`
- `row_count`
- `source_format`
- `loaded_at`
- `fingerprint_kind`

`fingerprint_kind`:
- v1 CSV: `content_sha256`
- v2 Parquet: `parquet_meta_hash` (опционально strict mode: full content hash)
- v2 DuckDB: `duckdb_snapshot`

Маленький пример: sampling в dictionary telemetry

```python
def should_log_debug(event: str, dict_name: str, key_fingerprint: str) -> bool:
    raw = f"{event}:{dict_name}:{key_fingerprint}"
    bucket = int(sha256(raw.encode("utf-8")).hexdigest()[:8], 16) % 100
    if event == "lookup_miss":
        return bucket < 10
    if event == "lookup_hit":
        return bucket < 1
    return True
```

Маленький пример: startup-only reload и интеграция с AppContainer

```python
# connector/delivery/cli/dictionaries_container.py — DeclarativeContainer (не CR)

def dictionary_backend_resource(
    bundle: DictionaryDslRuntimeBundle,
    loader: CsvDictionaryLoader,
    settings: DictionaryRuntimeSettings,
) -> Iterator[PolarsDictionaryBackend]:
    backend = PolarsDictionaryBackend(bundle=bundle, settings=settings)
    loader.load_into(backend)   # eager: DslLoadError → fail-fast при init_resources()
    yield backend
    # teardown: нет (read-only in-memory)


class DictionaryContainer(containers.DeclarativeContainer):
    settings = providers.Dependency(instance_of=DictionaryRuntimeSettings)

    dsl_runtime = providers.Singleton(build_dictionary_dsl_runtime, settings=settings)
    csv_loader  = providers.Singleton(CsvDictionaryLoader)

    backend = providers.Resource(
        dictionary_backend_resource,
        bundle=dsl_runtime, loader=csv_loader, settings=settings,
    )
    provider = providers.Singleton(PolarsDictionaryProvider, backend=backend, settings=settings)


# connector/delivery/cli/containers.py — AppContainer монтирует DictionaryContainer
class AppContainer(containers.DeclarativeContainer):
    ...
    _dictionary_settings = providers.Callable(lambda s: s.dictionary, s=app_settings)
    dictionary = providers.Container(DictionaryContainer, settings=_dictionary_settings)
    ...

# _init_container_for_requirements(): provider неизменяем в пределах run
if req.requires_dictionaries:
    container.dictionary.backend.init()
    container.pipeline.dictionaries.override(container.dictionary.provider)
```

Маленький пример: lazy-load per dictionary (опция v1)

```python
# provider.get_dictionary("organizations") загружает CSV только при первом обращении
rows = provider.lookup("organizations", "org-001")
# повторные обращения к "organizations" идут из in-memory backend
```

Маленький пример: единый version contract

```python
version_info = {
    "dict_name": "organizations",
    "version_id": "orgs:7fbe31a1",
    "schema_hash": "8d2c...",
    "row_count": 128,
    "source_format": "csv",
    "loaded_at": "2026-02-19T18:02:11Z",
    "fingerprint_kind": "content_sha256",
}
```

### Закрытие открытых вопросов (10/10)

Ниже зафиксированы финальные решения по открытому пулу вопросов для v1 baseline.

1. **Scope `DictionaryProviderPort` в v1**:
   - фиксируем только `lookup`, `contains`, `canonicalize`;
   - `batch_lookup` не добавляем в контракт v1;
   - для v2 допускается опциональное расширение через отдельный capability/adapter, без ломки базового порта.

Маленький пример: отдельная capability для v2, не ломающая v1 API

```python
class BatchLookupCapable(Protocol):
    def batch_lookup(self, dict_name: str, keys: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]: ...
```

2. **Каноническая форма `datasets/registry.yml` для dictionaries**:
   - используем единую секцию `dictionaries.version + dictionaries.items`;
   - каждый item содержит минимум `spec` и `enabled`;
   - `items: {}` допустим и означает runtime с 0 словарей;
   - любые runtime/storage детали запрещены в registry (только control plane).

```yaml
dictionaries:
  version: 1
  items:
    organizations:
      spec: dictionaries/organizations.dictionary.yaml
      enabled: true
```

3. **Обязательные/опциональные поля `DictionarySpec` (Pydantic boundary)**:
   - обязательные: `dictionary`, `source.format`, `source.location`, `schema.key_column`, `schema.value_columns`;
   - опциональные: `source.csv.*` (`delimiter`, `has_header`, `encoding`), `schema.normalized_key`, `lookup.allow_duplicates`;
   - в v1 `source.format` ограничен `csv`.

4. **Точка wiring DI-container (Dictionary runtime)**:
   - `DictionaryContainer` — `DeclarativeContainer` в `dictionaries_container.py`,
     монтируется в `AppContainer` через `providers.Container(DictionaryContainer, ...)`;
   - единственный CR — `AppContainer` в `connector/delivery/cli/containers.py`;
   - контейнер не передается в domain/use-case; наружу выходит только `DictionaryProviderPort`;
   - `PipelineContainer.dictionaries` (уже существует как `providers.Object(None)`) переопределяется
     в `_init_container_for_requirements()` через `container.pipeline.dictionaries.override(...)`;
   - условная инициализация: `req.requires_dictionaries=True` → `container.dictionary.backend.init()`
     → eager CSV load → fail-fast при ошибке;
   - при `requires_dictionaries=False`: `PipelineContainer.dictionaries` остаётся `None`;
   - `build_enrich_deps()` в `DatasetSpec` и `EmployeesSpec` принимают `dictionaries` из
     stage context — без изменений в сигнатуре `build_pipeline_context()`.

5. **Taxonomy diagnostics кодов и зоны применения**:
   - `DICT_*` используется только для DSL/load/runtime init слоя словарей;
   - row-level lookup outcomes внутри enrich остаются в `ENRICH_*`;
   - исключаем смешение DICT и ENRICH кодов в одной и той же ответственности.

6. **Каноническая схема `report.context["dictionary"]`**:
   - обязательные поля: `backend`, `dictionaries_loaded`, `rows_loaded_total`, `lookup_total`, `lookup_hit`, `lookup_miss`, `lookup_error`, `dictionaries_detail`;
   - `dictionaries_detail`: `dict[str, {"rows": int, "lookup_hit": int, "lookup_miss": int, "lookup_error": int}]`;
   - для run без загруженных словарей `dictionaries_detail` фиксируется как пустой объект `{}`.
   - опциональные: `load_duration_ms`, `version_info` (list), `sampling_policy`.

```python
report.context["dictionary"] = {
    "backend": "polars",
    "dictionaries_loaded": 3,
    "rows_loaded_total": 128,
    "lookup_total": 420,
    "lookup_hit": 398,
    "lookup_miss": 20,
    "lookup_error": 2,
    "dictionaries_detail": {
        "organizations": {"rows": 128, "lookup_hit": 300, "lookup_miss": 10, "lookup_error": 1},
        "departments": {"rows": 45, "lookup_hit": 98, "lookup_miss": 10, "lookup_error": 1},
    },
}
```

7. **Политика `key_fingerprint` (без plaintext ключей)**:
   - алгоритм v1: `sha256(salt + normalized_key)` и короткий префикс (например 12 hex);
   - `salt` берется из runtime settings и не логируется;
   - plaintext key в logs/diagnostics запрещен.

```python
fingerprint = sha256((salt + normalized_key).encode("utf-8")).hexdigest()[:12]
```

8. **Deterministic sampling policy для DEBUG lookup**:
   - sampling вычисляется детерминированно от `event + dict_name + key_fingerprint` (без RNG);
   - пороги сохраняются: `hit=1%`, `miss=10%`;
   - это гарантирует воспроизводимость между запусками для одинаковых входов.

```python
bucket = int(sha256(f"{event}:{dict_name}:{fp}".encode()).hexdigest()[:8], 16) % 100
should_log = (event == "lookup_hit" and bucket < 1) or (event == "lookup_miss" and bucket < 10)
```

9. **Явные trigger-критерии миграции на v2 (Polars+DuckDB+Parquet)**:
   - объём словаря устойчиво превышает профиль v1 (например > 100k строк или > 50 MB на словарь);
   - нужны SQL-temporal/aggregation сценарии;
   - требуется incremental update/versioned storage beyond CSV discipline.
   При выполнении любого из критериев инициируется ADR update для v2 rollout.

10. **Ownership-политика CSV snapshots (v1)**:
   - source of truth: файловые snapshots под управлением dataset owners;
   - обновление только атомарной заменой файла (`tmp -> rename`) между runs;
   - rollback через хранение предыдущего snapshot + fingerprint в release artifacts;
   - runtime остается strictly read-only.

### Дополнительные решения перед максимальной v1 реализацией

1. **Модель спецификации словаря**:
   - используется только одна публичная модель: `DictionarySpec` (Pydantic);
   - runtime может собирать внутренние структуры, но без отдельного публичного контракта-двойника.

2. **Алгоритм `schema_hash` и `version_id`**:
   - `schema_hash` = `sha256(canonical_json(schema_subset))`, где `schema_subset` включает:
     `dictionary`, `source.format`, `schema.key_column`, `schema.value_columns`,
     `schema.normalized_key.ops`, `lookup.allow_duplicates`;
   - `version_id` = `"{dict_name}:{schema_hash[:12]}:{content_sha256[:12]}"`;
   - canonical JSON сериализуется с `sort_keys=True`, без пробелов, в UTF-8.

```python
schema_hash = sha256(canonical_json(schema_subset).encode("utf-8")).hexdigest()
version_id = f"{dict_name}:{schema_hash[:12]}:{content_sha256[:12]}"
```

3. **Источник `key_fingerprint` salt и ротация**:
   - salt приходит только из runtime settings (`DictionaryRuntimeSettings`, env prefix `ANKEY_`);
   - минимальное поле: `dictionary_fingerprint_salt`;
   - ротация выполняется релизно (manual/ops), backward-совместимость fingerprint между salt-версиями не требуется;
   - в telemetry/report добавляется `fingerprint_salt_version` (без значения salt).

4. **CSV governance: где валидируем и кто владелец**:
   - CI/pre-merge: schema + fingerprint preflight для snapshot и spec;
   - runtime startup: повторная валидация файла (exists/readable/columns/fingerprint);
   - при несовпадении fingerprint runtime падает fail-fast строго с `DICT_SOURCE_FINGERPRINT_MISMATCH` (без fallback).

5. **Manifest для CSV snapshots (обязательный компонент v1)**:
   - путь: `datasets/dictionaries/manifest.yml` (единая точка входа);
   - ключ верхнего уровня: `version: 1`, далее `items.<dict_name>`;
   - для каждого словаря: `csv_path`, `content_sha256`, `schema_hash`, `row_count`, `updated_at_utc`, `owner`;
   - runtime сверяет `content_sha256` + `schema_hash` с фактом перед загрузкой.
   - manifest обязателен для всех `enabled` словарей в v1.

Генерация/владение manifest:
- source of truth и owner: dataset owners;
- manifest генерируется preflight-утилитой (CI и локально) вместе с пересчетом hash/row_count;
- обновление `manifest.yml` коммитится в одном change-set с обновлением CSV/spec.

Поведение runtime без manifest:
- файл отсутствует -> fail-fast с `DICT_SOURCE_MANIFEST_MISSING`;
- структура невалидна или отсутствует entry для enabled-словаря -> fail-fast с `DICT_SOURCE_MANIFEST_INVALID`;
- hash mismatch -> fail-fast с `DICT_SOURCE_FINGERPRINT_MISMATCH`.

```yaml
version: 1
items:
  organizations:
    csv_path: dictionaries/organizations.csv
    content_sha256: "0d7f..."
    schema_hash: "8d2c..."
    row_count: 128
    updated_at_utc: "2026-02-19T19:31:00Z"
    owner: "dataset-employees"
```

6. **Триггеры миграции v1 -> v2: hard + soft policy**:
   - hard trigger: любой словарь > 100k строк или > 50MB в 3 последовательных run;
   - hard trigger: benchmark-regression lookup p95 > 30% от baseline на стандартном профиле;
   - soft trigger: появление требований SQL temporal/aggregation;
   - при hard trigger обязателен ADR update и план миграции на v2.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Быстрый и понятный v1 под текущий размер словарей (100-200 строк).
- ✅ In-memory исполнение без тяжелого storage контура.
- ✅ Жестко зафиксированные границы ответственности упрощают миграцию.
- ✅ Domain/enrich остается стабильным и backend-agnostic.

**Недостатки (компромиссы)**:
- ⚠️ Нет SQL storage/query возможностей в v1.
- ⚠️ CSV требует отдельной дисциплины по версиям/обновлениям.
- ⚠️ При росте словарей потребуется переход на v2 backend.

**Альтернативы, которые отклонили для v1**:
- ❌ DuckDB в v1: избыточен для текущего объема словарей.
- ❌ SQLite в v1: не соответствует целевой модели дальнейшей эволюции.
- ❌ Одновременный запуск Polars+DuckDB в v1: лишняя сложность при текущих требованиях.

---

## 🛠️ Реализация

### Общее дерево модулей (v1 target)

```text
connector/
├── config/
│   └── app_settings.py                         # DictionaryRuntimeSettings (salt/sampling knobs)
├── domain/
│   ├── dictionary_dsl/
│   │   ├── specs.py                            # Pydantic DSL контракт словаря
│   │   ├── loader.py                           # Загрузка/валидация registry + spec
│   │   └── __init__.py
│   ├── ports/transform/dictionaries.py         # DictionaryProviderPort
│   ├── transform/providers/registry.py         # provider args -> вызов порта
│   └── diagnostics/core_catalog.py             # DICT_* codes
├── infra/
│   └── dictionaries/
│       ├── dsl_runtime.py                      # Компиляция runtime bundle
│       ├── loader_csv.py                       # Чтение CSV snapshots
│       ├── provider.py                         # Адаптер DictionaryProviderPort
│       ├── telemetry.py                        # structlog + report.context counters
│       ├── versioning.py                       # schema_hash/version_id/fingerprint
│       └── backends/polars_backend.py          # In-memory lookup engine
├── delivery/
│   └── cli/dictionaries_container.py           # DictionaryContainer (субконтейнер AppContainer)
└── datasets/
    ├── registry.yml                            # секция dictionaries
    └── employees/spec.py                       # Проброс deps.dictionaries

tests/
├── unit/
│   ├── domain/dictionary_dsl/...
│   ├── infra/dictionaries/...
│   └── domain/diagnostics/...
├── integration/
│   └── transform/dictionary_runtime/...
├── e2e/
│   └── cli/dictionary_enrich/...
└── benchmarks/
    └── dictionary_runtime/...
```

### Ключевые файлы (to be)

| Файл | Изменение |
|------|-----------|
| `connector/config/app_settings.py` | `DictionaryRuntimeSettings` (salt/sampling/runtime knobs) |
| `connector/domain/ports/transform/dictionaries.py` | Стабилизация контракта порта |
| `connector/domain/transform/providers/registry.py` | Проброс lookup-аргументов |
| `connector/domain/dictionary_dsl/specs.py` | Pydantic-модели dictionary DSL |
| `connector/domain/dictionary_dsl/loader.py` | Loader dictionary registry/spec |
| `connector/domain/dictionary_dsl/__init__.py` | Public API dictionary DSL |
| `connector/infra/dictionaries/dsl_runtime.py` | Runtime bundle dictionary DSL |
| `connector/infra/dictionaries/loader_csv.py` | CSV loader для словарей |
| `connector/infra/dictionaries/backends/polars_backend.py` | In-memory Polars backend |
| `connector/infra/dictionaries/provider.py` | Адаптер порта поверх Polars backend |
| `connector/infra/dictionaries/telemetry.py` | Structlog logging + runtime counters/report context |
| `connector/infra/dictionaries/versioning.py` | Version contract + fingerprint strategies (v1/v2) |
| `connector/delivery/cli/dictionaries_container.py` | Новый `DictionaryContainer(DeclarativeContainer)`: `dsl_runtime` (Singleton), `csv_loader` (Singleton), `backend` (Resource), `provider` (Singleton) |
| `connector/delivery/cli/containers.py` | Обновить `AppContainer`: добавить `dictionary = providers.Container(DictionaryContainer, ...)`; обновить `_init_container_for_requirements()`: добавить ветку `requires_dictionaries` |
| `connector/domain/diagnostics/core_catalog.py` | Регистрация `DICT_*` кодов |
| `connector/datasets/spec.py` | Обновить: `build_enrich_deps()` базового `DatasetSpec` — `dictionaries` приходит из `PipelineContainer.dictionaries` через stage context |
| `connector/datasets/employees/spec.py` | Обновить: `EmployeesSpec.build_enrich_deps()` — принять и пробросить `dictionaries` в `TransformProviderDeps` |
| `datasets/registry.yml` | Добавить секцию `dictionaries` |

### Инварианты

1. Domain слой не импортирует Polars и DuckDB.
2. Lookup идет только через `DictionaryProviderPort`.
3. Backend не содержит бизнес-решений enrich.
4. В v1 запись в словари в runtime запрещена (read-only snapshots).
5. DI-container не утекает за пределы composition root.
6. Hot path `contains/exists` в Polars backend допускает set-based key index (amortized `O(1)`).

---

## 🧪 Валидация решения

### Unit

- Pydantic-валидация `DictionaryRegistrySpec`/`DictionarySpec` и nested-моделей `source/schema/lookup`.
- Валидация provider args для `dictionary.by_key` (`dict_name`, `at`, `fields`, `limit`) и reject unknown args.
- `lookup/contains/canonicalize` для Polars backend, включая `fields` projection и `limit`.
- `contains/exists` hot path: проверка использования set-based key index и отсутствие полного
  DataFrame-скана на каждый запрос.
- CSV loader: missing file, missing columns, delimiter/header режимы, key normalization.
- CSV loader: encoding/BOM handling (`utf-8`/`utf-8-sig`), empty CSV -> warning path.
- CSV loader: duplicate key policy (`allow_duplicates=false` -> `DICT_SCHEMA_INVALID`,
  `allow_duplicates=true` -> multi-row lookup).
- Normalization parity: одинаковый результат `normalized_key.ops` на load-path и lookup-path.
- Normalization whitelist: reject неподдерживаемых ops в `normalized_key.ops`.
- Lazy-load policy: first-touch load одного словаря, отсутствие повторного IO на последующих lookup.
- Versioning: `schema_hash`, `content_sha256`, `version_id`, `fingerprint_kind` сериализация.
- Telemetry: `key_fingerprint` mask, deterministic sampling (`hit=1%`, `miss=10%`), отсутствие plaintext key.
- Diagnostics: mapping `DICT_*` -> `SystemErrorCode`, корректный `DslLoadError` wrapping.
- Diagnostics: mapping row-level dictionary outcomes:
  - miss -> `ENRICH_NO_CANDIDATES`,
  - backend/runtime error -> `ENRICH_PROVIDER_ERROR`,
  - `deps.dictionaries is None` -> `ENRICH_PROVIDER_ERROR`,
  - unknown `dict_name` in non-empty runtime -> `ENRICH_PROVIDER_ERROR`,
  - unknown `dict_name` при `items: {}` -> `ENRICH_NO_CANDIDATES`.
- Report context: обязательные поля секции `dictionary`, корректные агрегированные и per-dictionary
  счетчики (`dictionaries_detail`).
- **DictionaryContainer**: `init_resources()` не бросает при корректных данных;
  `provider()` возвращает `DictionaryProviderPort`-совместимый экземпляр;
  два вызова `provider()` возвращают один и тот же объект (Singleton);
  `shutdown_resources()` завершается без ошибок (teardown = no-op).

### Integration

- `dictionary_dsl.loader` + `dsl_runtime` + `loader_csv` + `provider` как единая цепочка.
- Wiring: `delivery` передает `DictionaryProviderPort` в `TransformProviderDeps`.
- Enrich provider registry: `dictionary.by_key` вызывает порт с контрактными args.
- Совместимость контракта: одинаковое поведение порта для v1 backend и mock v2 backend.
- Startup fail-fast при broken spec/CSV/fingerprint mismatch.
- Lazy-mode: ошибка неиспользованного словаря не валит run до первого обращения к нему.
- **DictionaryContainer lifecycle**: eager-mode — `init_resources()` падает с `DslLoadError`
  при broken CSV; `shutdown_resources()` не бросает (teardown = no-op).
  Паттерн теста по аналогии с `test_sqlite_container.py`:

```python
def test_dictionary_container_init(tmp_path, sample_dictionary_csv):
    container = DictionaryContainer()
    container.settings.override(DictionaryRuntimeSettings(...))
    try:
        container.init_resources()
        provider = container.provider()
        assert isinstance(provider, PolarsDictionaryProvider)
        assert container.provider() is container.provider()  # Singleton
    finally:
        container.shutdown_resources()


def test_dictionary_container_fail_fast_on_broken_csv(tmp_path):
    """Broken CSV (missing key column) → DslLoadError при init_resources()."""
    container = DictionaryContainer()
    container.settings.override(DictionaryRuntimeSettings(...))
    with pytest.raises(DslLoadError, match="DICT_SCHEMA_INVALID"):
        container.init_resources()
    container.shutdown_resources()


def test_dictionary_container_fail_fast_on_fingerprint_mismatch(tmp_path):
    """Fingerprint mismatch → DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH) при init."""
    ...


def test_dictionary_container_shutdown_is_noop(tmp_path, sample_dictionary_csv):
    """shutdown_resources() после init не бросает (teardown = no-op)."""
    container = DictionaryContainer()
    container.settings.override(DictionaryRuntimeSettings(...))
    container.init_resources()
    container.shutdown_resources()  # не должно падать
```

### E2E

- CLI сценарий enrich на тестовом dataset с реальным `datasets/registry.yml` + `*.dictionary.yaml` + CSV snapshot.
- Проверка, что `report.context["dictionary"]` заполнен и содержит version metadata.
- Негативный сценарий: поврежденный словарь приводит к корректному `DICT_*` diagnostic в итоговом report.
- Негативный сценарий: неправильные args в enrich DSL блокируются до runtime.

### Performance / Benchmark

- `pyperf` профиль `v1_small` (100-200 строк): startup load + lookup hit/miss.
- `pyperf` профиль `v1_upper` (10k строк): projection/limit нагрузка и hit/miss ratio.
- `pyperf` профиль `migration_signal` (100k строк): не-блокирующий, для отслеживания v2 trigger.
- `pyperf` профиль `v1_lazy_cold_start`: latency первого обращения к словарю в lazy-mode.
- `pyperf` профиль `v1_lazy_warm_hit`: latency повторного hit после lazy-load.
- `pyperf` профиль `v1_exists_hot_path`: latency `contains/exists` hit/miss с key-set индексом.
- Gating правило CI: regression медианы > 30% от baseline для `v1_small`/`v1_upper` — fail.
- Trend правило: 3 последовательных деградации или hard trigger по объему инициируют ADR update на v2 rollout.

**Критерий миграционной готовности**:
- Смена backend в wiring не требует изменений в domain/enrich DSL.

---

## ⚠️ Риски и ограничения

**Известные ограничения v1**:
- Нет встроенного SQL-temporal/aggregation слоя.
- Нет встроенного storage-versioning уровня DuckDB.
- Нет hot-reload в рамках одного run (startup-only модель).

**Риски**:
- ⚠️ Рост объема словарей за пределы in-memory профиля → Митигация: переход на v2 backend.
- ⚠️ Неконсистентные CSV snapshots → Митигация: manifest-валидация и pre-run checks.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| Enrich DSL правила | Без изменений контракта | Продолжать использовать `dictionary.by_key` |
| Dataset spec wiring | Новый dependency | Передавать `dictionaries` в `TransformProviderDeps` |
| Delivery containers | Новые providers | Инициализировать CSV loader + Polars provider |
| Future v2 backend | Планируемое расширение | Добавить DuckDB storage/query + Parquet, сохранив Polars execution |

---

## 📚 Документация

**План обновления docs**:
- `docs/dev/layers/transform/enrich-core.md` (новый документ) — словарный runtime flow.
- `docs/dev/layers/transform/enrich-dsl.md` (новый документ) — контракт `dictionary.by_key`.
- `docs/dev/layers/resolver/resolve-core.md` — ссылка на общий dictionary port boundary.

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-001](./TRANSFORM-PROBLEM-001-enrich-dictionary-runtime-gap.md)
- [Resolve Core](../../dev/layers/resolver/resolve-core.md)
- `connector/domain/ports/transform/dictionaries.py`
- `connector/domain/transform/providers/registry.py`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Решение предложено и зафиксировано в ADR |
| 2026-02-19 | Обновлено: v1 = Polars + CSV, v2 = Polars + DuckDB + Parquet |
| 2026-02-19 | Добавлен Dictionary DSL flow: YAML control plane + Pydantic boundary validation |
| 2026-02-19 | Зафиксирован локальный DI-container (dependency-injector) только для dictionary runtime |
| 2026-02-19 | Добавлен observability/diagnostics контракт: report context + `DICT_*` + structlog policy |
| 2026-02-19 | Зафиксирована operational policy: sampling, startup-only reload, единый versioning contract v1/v2 |
| 2026-02-19 | Закрыт пул из 10 открытых вопросов: порт, DSL schema, DI wiring, diagnostics/report/logging, v2 triggers, CSV ownership policy |
| 2026-02-19 | Устранены несостыковки: единая `DictionarySpec` модель, удален `infra/dictionaries/cache.py`, зафиксирован args-контракт `dictionary.by_key` |
| 2026-02-19 | Добавлены: общее дерево модулей v1 target, полный тестовый контур (unit/integration/e2e/benchmark), hard+soft v2 migration policy |
| 2026-02-19 | Уточнено: fingerprint mismatch только через `DICT_SOURCE_FINGERPRINT_MISMATCH` (без fallback), предложен единый `datasets/dictionaries/manifest.yml` |
| 2026-02-19 | Зафиксирована политика diagnostics placement: `DICT_*` в v1 только в `core_catalog.py`, без отдельного dictionary-catalog модуля |
| 2026-02-20 | Добавлены provider-контракты `dictionary.exists_by_key` и `dictionary.canonicalize`; зафиксировано, что `contains` не используется в enrich exists-path |
| 2026-02-20 | Актуализирован DI-контракт: `bootstrap.py` удалён, composition root — `containers.py`; `DictionaryDslRuntime` → `DictionaryDslRuntimeBundle`; зафиксирована точка интеграции `build_pipeline_context()` и цепочка `DatasetSpec` / `EmployeesSpec.build_enrich_deps()` |
| 2026-02-20 | Уточнен manifest-контракт v1: `datasets/dictionaries/manifest.yml` обязателен, добавлены правила генерации/валидации и fail-fast поведение при отсутствии/невалидности |
| 2026-02-20 | Добавлена опция lazy-load для v1 (default остаётся eager startup-load), уточнены тестовые и benchmark сценарии для cold/warm path |
| 2026-02-20 | Зафиксирован row-level mapping `ENRICH_*` для dictionary provider: miss -> `ENRICH_NO_CANDIDATES`, backend/unknown dict -> `ENRICH_PROVIDER_ERROR` |
| 2026-02-20 | Уточнен контракт `normalized_key.ops`: reuse общего DSL registry, whitelist операций и симметричное применение на load-path и lookup-path |
| 2026-02-20 | Добавлена секция concurrency model: v1 single-threaded, telemetry counters без thread-safety guarantees; требования к v2 для конкурентного исполнения |
| 2026-02-20 | Уточнены CSV edge cases: encoding/BOM, пустой CSV как valid dictionary (warning), политика дублей ключей через `allow_duplicates` |
| 2026-02-20 | Добавлен явный Pydantic-контракт `DictionaryRegistrySpec`/`DictionaryRegistryItemSpec` и инварианты `version/items` для `datasets/registry.yml` |
| 2026-02-20 | Зафиксирован graceful degradation контракт: без секции `dictionaries` -> `dictionaries=None` и `ENRICH_PROVIDER_ERROR`; при `items: {}` -> runtime с 0 словарей и miss->`ENRICH_NO_CANDIDATES` |
| 2026-02-20 | Зафиксирована v1 оптимизация hot path `contains/exists`: допускается set-based key index (`O(1)`), benchmark-профиль `v1_exists_hot_path` добавлен в требования |
| 2026-02-20 | Зафиксирован lifecycle-контракт инициализации: dictionary container поднимается после settings и до `build_pipeline_context()`, ошибки инициализации dictionary runtime завершают run fail-fast |
| 2026-02-20 | Расширен контракт `report.context[\"dictionary\"]`: добавлен обязательный per-dictionary breakdown `dictionaries_detail` с метриками rows/hit/miss/error |
| 2026-02-23 | Исправлена DI-стратегия: `DictionaryContainer` — субконтейнер `AppContainer` (не автономный CR); `dictionaries_container.py` содержит `DeclarativeContainer`, монтируется через `providers.Container(...)` |
| 2026-02-23 | Lifecycle backend: `PolarsDictionaryBackend` изменён с `Singleton` на `Resource` — fail-fast eager CSV load при `init_resources()`; teardown = no-op |
| 2026-02-23 | Зафиксирована ответственность модулей: `dsl_runtime.py` — pure transformer specs→bundle, резолюция ops через OperationRegistry (не whitelist); `telemetry.py` — когезивный класс logging+counters с явным trade-off |
| 2026-02-23 | Whitelist `normalized_key.ops` перенесён в domain: `@field_validator` в `DictionaryNormalizedKeySpec` с константой `DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST` |
| 2026-02-23 | Добавлены integration-тесты `DictionaryContainer`: init/Singleton/fail-fast/shutdown паттерн по аналогии с `test_sqlite_container.py` |
