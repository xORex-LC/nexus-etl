# TRANSFORM-DEC-001: Справочная подсистема enrich (Polars v1, migration-ready для v2: Polars+DuckDB+Parquet)

> **Статус**: Предложено
> **Дата принятия**: 2026-02-19
> **Решает проблему**: [TRANSFORM-PROBLEM-001](./TRANSFORM-PROBLEM-001-enrich-dictionary-runtime-gap.md)
> **Участники решения**: @xorex

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

Для v1 принимается локальное применение `dependency-injector` только в Dictionary runtime
composition root.

Границы:
1. DI-контейнер создается и используется только на уровне wiring (`connector/delivery/cli/`).
2. Domain/use-case/stage-код не получает container как зависимость.
3. Внедрение зависимостей остается constructor-based через контракты (`DictionaryProviderPort`).
4. Legacy composition root `connector/delivery/cli/containers.py` не мигрируется; словарный
   DI-контейнер создаётся в отдельном `connector/delivery/cli/dictionaries_container.py`
   и интегрируется через параметр `dictionaries=` в `build_pipeline_context()`.

Lifecycle провайдеров (v1):
- `DictionaryDslRuntimeBundle` — `Singleton`.
- `CsvDictionaryLoader` — `Singleton`.
- `PolarsDictionaryBackend` — `Singleton`.
- `DictionaryProviderPort` адаптер — `Singleton`.

Переход v1 -> v2:
- container API для потребителей не меняется;
- в DI-графе меняются только infra-провайдеры backend/storage;
- wiring остальных слоев остается неизменным.

### Карта ответственности (модуль/класс/метод)

- **Модуль `connector/domain/dictionary_dsl/specs.py`**:
  - Обязан: валидировать конфигурацию словаря (имя, путь CSV, ключ, колонки).
  - Запрещено: читать данные и выполнять lookup.
- **Модуль `loader_csv.py`**:
  - Обязан: читать CSV и создавать in-memory представление словаря.
  - Запрещено: бизнес-валидация enrich-правил.
- **Класс `PolarsDictionaryProvider`**:
  - Обязан: реализовать `DictionaryProviderPort`.
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
class DictionarySourceCsvSpec(DslBaseModel):
    delimiter: str = ","
    has_header: bool = True


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
- вложенные модели `source/schema/lookup`.

Инварианты, которые покрывает Pydantic:
1. `dictionary` не пустой и уникальный в рамках registry.
2. `source.format=csv` в v1, `source.location` обязателен.
3. `key_column` не входит в конфликт с `value_columns`.
4. `value_columns` не пустой.
5. `normalized_key.ops` валидируется как список `OperationCall`.

Все ошибки загрузки/валидации оборачиваются в `DslLoadError` с кодами `DICT_DSL_*`.
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
5. Построить runtime bundle (`DictionaryDslRuntimeBundle`: `dict_name -> compiled config`).
6. Загрузить CSV snapshots в Polars backend.
7. Собрать `DictionaryProviderPort` адаптер.
8. Передать через `dictionaries=` в `build_pipeline_context()` (`containers.py`);
   функция пробрасывает его в `dataset_spec.build_enrich_deps(dictionaries=...)`.
9. Enrich `dictionary.by_key` использует только порт.

### Observability и Diagnostics для Dictionary слоя

Dictionary слой использует существующие контуры report/diagnostics, но с отдельной зоной
ответственности:

1. **Report**:
   - row-level item'ы не добавляются из dictionary runtime;
   - агрегированные метрики пишутся в `report.context["dictionary"]`.
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
- `DICT_SOURCE_FINGERPRINT_MISMATCH` -> `SystemErrorCode.DATA_INVALID`
- `DICT_SCHEMA_INVALID` -> `SystemErrorCode.DATA_INVALID`
- `DICT_RUNTIME_INIT_FAILED` -> `SystemErrorCode.INTERNAL_ERROR`

Политика размещения diagnostics-кодов:
- v1: `DICT_*` регистрируются только в `connector/domain/diagnostics/core_catalog.py`;
- отдельный dictionary-catalog модуль не вводится в v1;
- выделение в отдельный модуль допускается только при росте таксономии (например, >20
  dictionary-специфичных кодов) или при plugin-доставке layer-catalog.

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
3. **Versioning contract (v1/v2 единый)**:
   - единый контракт версии сохраняется в report/log/diagnostics;
   - меняется только стратегия вычисления fingerprint по формату источника.

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

Маленький пример: startup-only reload и интеграция с composition root

```python
# dictionaries_container.py — строит провайдер один раз
bundle = load_dictionary_dsl_runtime()           # -> DictionaryDslRuntimeBundle
provider = build_dictionary_provider(bundle)     # -> DictionaryProviderPort адаптер

# containers.py — build_pipeline_context() принимает провайдер снаружи
ctx = build_pipeline_context(
    ...,
    dictionaries=provider,   # Singleton, неизменяем в пределах run
)
# в пределах одного run provider неизменяем; новые данные — следующий run
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
   - опциональные: `source.csv.*`, `schema.normalized_key`, `lookup.allow_duplicates`;
   - в v1 `source.format` ограничен `csv`.

4. **Точка wiring локального DI-container (Dictionary runtime)**:
   - контейнер создается только в `connector/delivery/cli/dictionaries_container.py`;
   - контейнер не передается в domain/use-case;
   - наружу выходит только `DictionaryProviderPort`;
   - интеграция с существующим composition root: `build_pipeline_context()` в
     `connector/delivery/cli/containers.py` принимает параметр `dictionaries: DictionaryProviderPort | None`;
   - `build_enrich_deps()` в `DatasetSpec` и `EmployeesSpec` также расширяются этим параметром.

5. **Taxonomy diagnostics кодов и зоны применения**:
   - `DICT_*` используется только для DSL/load/runtime init слоя словарей;
   - row-level lookup outcomes внутри enrich остаются в `ENRICH_*`;
   - исключаем смешение DICT и ENRICH кодов в одной и той же ответственности.

6. **Каноническая схема `report.context["dictionary"]`**:
   - обязательные поля: `backend`, `dictionaries_loaded`, `rows_loaded_total`, `lookup_total`, `lookup_hit`, `lookup_miss`, `lookup_error`;
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

5. **Manifest для CSV snapshots (предложение к утверждению)**:
   - путь: `datasets/dictionaries/manifest.yml` (единая точка входа);
   - ключ верхнего уровня: `version: 1`, далее `items.<dict_name>`;
   - для каждого словаря: `csv_path`, `content_sha256`, `schema_hash`, `row_count`, `updated_at_utc`, `owner`;
   - runtime сверяет `content_sha256` + `schema_hash` с фактом перед загрузкой.

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
│   └── cli/dictionaries_container.py           # Локальный DI composition root
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
| `connector/delivery/cli/dictionaries_container.py` | Новый локальный DI-container: `load_dictionary_dsl_runtime` + `build_dictionary_provider` (Singleton) |
| `connector/delivery/cli/containers.py` | Обновить: `build_pipeline_context()` — добавить параметр `dictionaries: DictionaryProviderPort \| None = None` |
| `connector/domain/diagnostics/core_catalog.py` | Регистрация `DICT_*` кодов |
| `connector/datasets/spec.py` | Обновить: `build_enrich_deps()` базового `DatasetSpec` — добавить параметр `dictionaries` |
| `connector/datasets/employees/spec.py` | Обновить: `EmployeesSpec.build_enrich_deps()` — принять и пробросить `dictionaries` в `TransformProviderDeps` |
| `datasets/registry.yml` | Добавить секцию `dictionaries` |

### Инварианты

1. Domain слой не импортирует Polars и DuckDB.
2. Lookup идет только через `DictionaryProviderPort`.
3. Backend не содержит бизнес-решений enrich.
4. В v1 запись в словари в runtime запрещена (read-only snapshots).
5. DI-container не утекает за пределы composition root.

---

## 🧪 Валидация решения

### Unit

- Pydantic-валидация `DictionaryRegistrySpec`/`DictionarySpec` и nested-моделей `source/schema/lookup`.
- Валидация provider args для `dictionary.by_key` (`dict_name`, `at`, `fields`, `limit`) и reject unknown args.
- `lookup/contains/canonicalize` для Polars backend, включая `fields` projection и `limit`.
- CSV loader: missing file, missing columns, delimiter/header режимы, key normalization.
- Versioning: `schema_hash`, `content_sha256`, `version_id`, `fingerprint_kind` сериализация.
- Telemetry: `key_fingerprint` mask, deterministic sampling (`hit=1%`, `miss=10%`), отсутствие plaintext key.
- Diagnostics: mapping `DICT_*` -> `SystemErrorCode`, корректный `DslLoadError` wrapping.
- Report context: обязательные поля секции `dictionary`, корректные счетчики hit/miss/error.

### Integration

- `dictionary_dsl.loader` + `dsl_runtime` + `loader_csv` + `provider` как единая цепочка.
- Wiring: `delivery` передает `DictionaryProviderPort` в `TransformProviderDeps`.
- Enrich provider registry: `dictionary.by_key` вызывает порт с контрактными args.
- Совместимость контракта: одинаковое поведение порта для v1 backend и mock v2 backend.
- Startup fail-fast при broken spec/CSV/fingerprint mismatch.

### E2E

- CLI сценарий enrich на тестовом dataset с реальным `datasets/registry.yml` + `*.dictionary.yaml` + CSV snapshot.
- Проверка, что `report.context["dictionary"]` заполнен и содержит version metadata.
- Негативный сценарий: поврежденный словарь приводит к корректному `DICT_*` diagnostic в итоговом report.
- Негативный сценарий: неправильные args в enrich DSL блокируются до runtime.

### Performance / Benchmark

- `pytest-benchmark` профиль `v1_small` (100-200 строк): startup load + lookup hit/miss.
- `pytest-benchmark` профиль `v1_upper` (10k строк): projection/limit нагрузка и hit/miss ratio.
- `pytest-benchmark` профиль `migration_signal` (100k строк): не-блокирующий, для отслеживания v2 trigger.
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
| 2026-02-20 | Актуализирован DI-контракт: `bootstrap.py` удалён, composition root — `containers.py`; `DictionaryDslRuntime` → `DictionaryDslRuntimeBundle`; зафиксирована точка интеграции `build_pipeline_context()` и цепочка `DatasetSpec` / `EmployeesSpec.build_enrich_deps()` |
