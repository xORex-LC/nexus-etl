# Dictionary Delivery

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
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Адаптация backend к доменному порту, наблюдаемость операций через детерминированную телеметрию и сборка объектного графа через DI sub-container.

**Ключевая ответственность**:
- `PolarsDictionaryProvider` — адаптер `DictionaryProviderPort` поверх `PolarsDictionaryBackend` с интеграцией telemetry
- `DictionaryTelemetry` — structured logging без plaintext ключей, sampling debug событий, snapshot counters для отчётов
- `DictionaryContainer` — DI sub-container: lifecycle `backend` Resource (eager/lazy), wiring всех зависимостей, graceful disabled mode

**Расположение в кодовой базе**:
- `connector/infra/dictionaries/provider.py` — `PolarsDictionaryProvider` (port adapter)
- `connector/infra/dictionaries/telemetry.py` — `DictionaryTelemetry` (observability)
- `connector/delivery/cli/dictionaries_container.py` — `DictionaryContainer` (DI wiring)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/infra/dictionaries/
├── provider.py         # PolarsDictionaryProvider: port adapter + telemetry integration
└── telemetry.py        # DictionaryTelemetry: counters + structured logging + snapshot

connector/delivery/cli/
└── dictionaries_container.py  # DictionaryContainer: DI wiring + lifecycle
    ├── DictionaryContainer             # DeclarativeContainer subclass
    ├── dictionary_backend_resource()   # Resource generator (eager/lazy policy)
    ├── _load_runtime_bundle_optional() # DSL compile step (optional mode)
    ├── _build_dictionary_telemetry()   # Telemetry factory
    └── _build_csv_loader()             # Loader factory with telemetry callback
```

**Слои ответственности**:

| Компонент | Уровень | Ответственность |
|-----------|---------|----------------|
| `PolarsDictionaryProvider` | Infra adapter | Реализует `DictionaryProviderPort`, делегирует в backend, вызывает telemetry |
| `DictionaryTelemetry` | Infra observability | Counters, structlog, key fingerprinting, snapshot |
| `DictionaryContainer` | Delivery (DI) | Object graph, lifecycle, disabled mode, eager/lazy выбор |

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Dictionary Delivery Class Diagram](../../uml/dictionary/dictionary_delivery_class.png) | Структура Provider, Telemetry, Container |
| Sequence | [Lookup with Telemetry](../../uml/dictionary/dictionary_delivery_sequence_lookup.png) | Полный путь вызова lookup через provider |
| Activity | [Container Init](../../uml/dictionary/dictionary_delivery_activity_container.png) | Lifecycle DI container (eager/lazy/disabled) |

**PlantUML исходники**: `docs/uml/dictionary/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Adapter (Port Implementation)

**Где применяется**: `PolarsDictionaryProvider` адаптирует `PolarsDictionaryBackend` (инфраструктурный класс) к `DictionaryProviderPort` (доменный Protocol).

**Реализация в коде**:
- **Port**: `DictionaryProviderPort` в `connector/domain/ports/transform/dictionaries.py`
- **Adapter**: `PolarsDictionaryProvider` в `provider.py:20`
- **Backend**: `PolarsDictionaryBackend` в `backends/polars_backend.py`

**Пример использования**:
```python
# Domain видит только DictionaryProviderPort
class EnrichEngine:
    def __init__(self, dict_provider: DictionaryProviderPort) -> None:
        self._dict = dict_provider  # Не знает о PolarsDictionaryProvider

# Delivery конфигурирует конкретный адаптер
provider = PolarsDictionaryProvider(backend=backend, telemetry=telemetry)
# provider implements DictionaryProviderPort (structural Protocol)
```

**Зачем**: Domain не зависит от Polars. Если в v2 появится DuckDB backend — достаточно создать `DuckDbDictionaryProvider`, domain не меняется.

---

#### Паттерн 2: Decorator / Cross-Cutting Concern (Telemetry Wrapping)

**Где применяется**: `PolarsDictionaryProvider` оборачивает каждый вызов backend в telemetry логику.

**Реализация в коде**:
- **Pattern**: `try/except` с `record_lookup_result()` / `record_lookup_error()` в `provider.py:39-83`
- **Key fingerprinting**: `_safe_key_fingerprint()` в `provider.py:169` — получает fingerprint до вызова backend, не передаёт plaintext в telemetry

**Пример**:
```python
def lookup(self, dict_name, key, ...):
    key_fingerprint = self._safe_key_fingerprint(dict_name=dict_name, value=key)
    try:
        rows = self._backend.lookup(dict_name, key, ...)
    except Exception as exc:
        self._telemetry.record_lookup_error(dict_name, op="lookup",
                                            key_fingerprint=key_fingerprint, error=exc)
        raise  # Не подавляем ошибку!
    self._telemetry.record_lookup_result(dict_name, op="lookup",
                                          hit=bool(rows), ...)
    return rows
```

**Зачем**: Чистое разделение: backend отвечает за lookup, provider — за наблюдаемость. Ошибки backend не подавляются и не модифицируются.

---

#### Паттерн 3: Deterministic Sampling (Hash-Based)

**Где применяется**: `DictionaryTelemetry._should_sample_debug()` — детерминированный sampling debug событий.

**Реализация в коде**:
- **Bucket**: `_sample_bucket()` в `telemetry.py:291` — `SHA-256(event|dict_name|key_fingerprint)[:4]` → `int % 100`
- **Sample check**: `bucket < percent` — детерминированный, reproducible

**Пример**:
```python
# При lookup_hit_sample_percent=1:
# SHA-256("lookup_hit|organizations|abc123ef")[:4] → int → % 100
# Если результат < 1 → log
# Один и тот же ключ всегда попадает или не попадает в sample

# → Reproducible: повторный запуск даёт одинаковое поведение
# → Не random: нет зависимости от random seed или времени
```

**Зачем**: Детерминированность важна для отладки — воспроизводимые результаты при одних и тех же данных. Нет drift между запусками.

---

#### Паттерн 4: Resource Lifecycle (dependency-injector Resource)

**Где применяется**: `DictionaryContainer.backend` объявлен как `providers.Resource` — имеет явный init/teardown lifecycle.

**Реализация в коде**:
- **Resource generator**: `dictionary_backend_resource()` в `dictionaries_container.py:169`
- **Init**: создание backend + eager/lazy load setup
- **Teardown**: no-op (read-only in-memory)

**Пример**:
```python
def dictionary_backend_resource(...) -> Iterator[PolarsDictionaryBackend | None]:
    backend = PolarsDictionaryBackend(bundle=dsl_runtime_bundle)
    if load_strategy == "eager":
        csv_loader.load_into(backend)  # Загрузка при init
    elif load_strategy == "lazy":
        backend.set_lazy_loader(...)
    yield backend               # ← контейнер использует backend
    # teardown: нет явных действий (in-memory, GC cleanup)
```

**Зачем**: Явный lifecycle позволяет `AppContainer` управлять порядком инициализации — `backend` инициализируется до `provider`.

---

#### Паттерн 5: Null Object (Disabled Mode)

**Где применяется**: При отсутствии секции `dictionaries` в registry контейнер возвращает `None` вместо реального provider.

**Реализация в коде**:
- `_load_runtime_bundle_optional()` → `None` если disabled
- `dictionary_backend_resource()` → `yield None` если `bundle is None`
- `_build_provider_or_none()` → `None` если `backend is None`

**Пример**:
```python
# При disabled mode:
provider = container.provider()   # → None
# EnrichEngine должен обрабатывать None:
if provider is not None:
    rows = provider.lookup(...)
else:
    rows = []  # Словари недоступны
```

**Зачем**: Graceful degradation — приложение работает без словарей, не падая при старте. Полезно для деплоя без словарных данных.

### Диаграмма зависимостей

```
[DictionaryConfig settings]  ←  AppContainer.settings
         ↓
[DictionaryContainer]
    ├── dsl_runtime_bundle (Singleton)
    │       ← _load_runtime_bundle_optional(datasets_root)
    │           ← load_optional_dictionary_registry_spec_for_runtime()  [DSL]
    │           ← load_enabled_dictionary_specs_for_runtime()            [DSL]
    │           ← load_dictionary_manifest_spec_for_runtime()            [DSL]
    │           ← build_dictionary_dsl_runtime()                         [Core]
    │
    ├── telemetry (Singleton)
    │       ← _build_dictionary_telemetry(settings)
    │
    ├── csv_loader (Singleton)
    │       ← _build_csv_loader(datasets_root, telemetry)
    │           on_dictionary_loaded=telemetry.record_dictionary_loaded
    │
    ├── backend (Resource)
    │       ← dictionary_backend_resource(bundle, csv_loader, settings, telemetry)
    │           IF bundle is None → yield None  (disabled mode)
    │           IF eager: csv_loader.load_into(backend)
    │           IF lazy:  backend.set_lazy_loader(lambda: csv_loader.load_dictionary_into(...))
    │           telemetry.record_runtime_initialized(...)
    │           yield backend
    │
    └── provider (Singleton)
            ← _build_provider_or_none(backend, telemetry)
                IF backend is None → None
                ELSE → PolarsDictionaryProvider(backend, telemetry)

[PolarsDictionaryProvider]
    ├── _backend: PolarsDictionaryBackend
    └── _telemetry: DictionaryTelemetry
        ├── lookup(dict_name, key, ...) → record_lookup_result/error
        ├── contains(dict_name, value) → record_lookup_result/error
        └── canonicalize(dict_name, value) → record_lookup_result/error
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `PolarsDictionaryProvider` | Port adapter: backend + telemetry | `lookup()`, `contains()`, `canonicalize()`, `_safe_key_fingerprint()` |
| `DictionaryTelemetry` | Observability: counters + logs + snapshot | `build_key_fingerprint()`, `record_lookup_result()`, `record_lookup_error()`, `record_runtime_initialized()`, `record_dictionary_loaded()`, `snapshot()` |
| `DictionaryContainer` | DI sub-container | Providers: `dsl_runtime_bundle`, `telemetry`, `csv_loader`, `backend`, `provider` |

### Функции DI Container

| Функция | Назначение |
|---------|-----------|
| `_load_runtime_bundle_optional()` | Optional compile DSL → bundle (None = disabled) |
| `_build_dictionary_telemetry()` | Telemetry factory из `DictionaryConfig` |
| `_build_csv_loader()` | Loader factory с telemetry callback |
| `dictionary_backend_resource()` | Resource generator: init + eager/lazy policy |
| `_build_provider_or_none()` | Provider factory (None если backend=None) |

---

## 🗂️ Модели данных

### Class: `DictionaryTelemetry`

**Назначение**: Centralized observability объект — собирает counters, структурированные логи и готовит snapshot для отчётов. Не зависит от delivery/DI.

**Конфигурация**:
```python
telemetry = DictionaryTelemetry(
    fingerprint_salt="secret-salt-value",    # Для HMAC-like fingerprinting ключей
    fingerprint_prefix_len=12,               # Длина hex-prefix fingerprint (default: 12)
    backend="polars",                        # Для contextual logging
    lookup_hit_sample_percent=1,             # % hit-событий для debug log (0–100)
    lookup_miss_sample_percent=10,           # % miss-событий для debug log (0–100)
)
```

**Внутренние структуры**:
```python
@dataclass
class _LookupCounters:            # Накопитель counters (mutable)
    lookup_total: int = 0
    lookup_hit: int = 0
    lookup_miss: int = 0
    lookup_error: int = 0

@dataclass
class _DictionaryRuntimeMetadata: # Per-dictionary runtime метаданные
    row_count: int | None
    fingerprint_kind: str | None
    version_info: dict | None
    anomalies: list[dict]

# В DictionaryTelemetry:
self._aggregate: _LookupCounters              # Aggregate по всем словарям
self._per_dictionary: dict[str, _LookupCounters]  # Per-dictionary counters
self._metadata_by_dict: dict[str, _DictionaryRuntimeMetadata]  # Per-dict metadata
self._anomalies: list[dict]                   # Глобальный список anomaly events
```

**Lifecycle**:
1. **Создание**: `_build_dictionary_telemetry(settings)` в контейнере
2. **Инициализация runtime**: `record_runtime_initialized()` при `dictionary_backend_resource()`
3. **Загрузка словарей**: `record_dictionary_loaded(event)` через callback
4. **Использование**: `record_lookup_result/error()` при каждом вызове Provider
5. **Snapshot**: `snapshot()` для включения в report context

**Инварианты**:
- `_aggregate` учитывает КАЖДУЮ операцию (все словари суммарно)
- `_per_dictionary[name]` учитывает только операции по конкретному словарю
- Fingerprint salt никогда не логируется и не возвращается наружу
- `lookup_hit_sample_percent` и `lookup_miss_sample_percent` ∈ [0, 100]

---

### Class: `PolarsDictionaryProvider`

**Назначение**: Thin adapter, реализующий `DictionaryProviderPort` поверх `PolarsDictionaryBackend` с telemetry cross-cutting.

**Конфигурация**:
```python
provider = PolarsDictionaryProvider(
    backend=polars_dictionary_backend,  # Required
    telemetry=dictionary_telemetry,     # Required
)
```

**Контракт метода `_safe_key_fingerprint()`**:
```python
def _safe_key_fingerprint(self, *, dict_name: str, value: Any) -> str:
    """
    Получить fingerprint нормализованного ключа без влияния на основной path.
    - Ошибки нормализации/резолва spec не ломают бизнес-операцию.
    - В telemetry всегда уходит fingerprint, но не plaintext.
    """
    normalized_value = value
    try:
        compiled = self._backend.bundle.get(dict_name)
        normalized_value = compiled.normalize_key(value)
    except Exception:
        normalized_value = value  # Fallback: fingerprint от raw key
    return self._telemetry.build_key_fingerprint(normalized_value)
```

**Зачем normaliz перед fingerprint**: Fingerprint должен быть консистентен с index-key — если lookup нормализует " ORG-1 " → "org-1", то и fingerprint должен быть от "org-1", иначе hit по одному и тому же ключу будет иметь разные fingerprints.

---

### DI: `DictionaryContainer`

**Назначение**: `dependency_injector.DeclarativeContainer` sub-container — объявляет и связывает все зависимости dictionary runtime.

**Структура контейнера**:
```python
class DictionaryContainer(containers.DeclarativeContainer):

    # Внешние зависимости (инъецируются AppContainer'ом)
    settings = providers.Dependency(instance_of=DictionaryConfig)
    datasets_root = providers.Dependency()

    # Singleton: DSL компиляция (без IO)
    dsl_runtime_bundle = providers.Singleton(
        _load_runtime_bundle_optional,
        datasets_root=datasets_root,
    )

    # Singleton: Telemetry объект
    telemetry = providers.Singleton(
        _build_dictionary_telemetry,
        settings=settings,
    )

    # Singleton: CSV loader с telemetry callback
    csv_loader = providers.Singleton(
        _build_csv_loader,
        datasets_root=datasets_root,
        telemetry=telemetry,
    )

    # Resource: Backend с lifecycle (eager/lazy init, no-op teardown)
    backend = providers.Resource(
        dictionary_backend_resource,
        dsl_runtime_bundle=dsl_runtime_bundle,
        csv_loader=csv_loader,
        settings=settings,
        telemetry=telemetry,
    )

    # Singleton: Provider (адаптер порта)
    provider = providers.Singleton(
        _build_provider_or_none,
        backend=backend,
        telemetry=telemetry,
    )
```

**Lifecycle порядок инициализации** (при `container.init_resources()`):
1. `settings` и `datasets_root` — инъецируются извне (от AppContainer)
2. `dsl_runtime_bundle` — DSL compile (YAML → Pydantic → bundle)
3. `telemetry` — создание telemetry объекта
4. `csv_loader` — создание loader с telemetry callback
5. `backend` (**Resource**) — `dictionary_backend_resource()`:
   - Проверка disabled mode
   - `telemetry.record_runtime_initialized()`
   - Eager: `csv_loader.load_into(backend)`
   - Lazy: `backend.set_lazy_loader(...)`
6. `provider` — `PolarsDictionaryProvider(backend, telemetry)` или `None`

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод/Функция | Строк | Сложность | Назначение |
|---------------|-------|-----------|------------|
| `dictionary_backend_resource()` | 47 | O(n) eager | Resource generator: init + load policy |
| `_load_runtime_bundle_optional()` | 30 | O(n) | DSL compile с optional mode |
| `DictionaryTelemetry.snapshot()` | 38 | O(d) | Serialize counters + metadata |
| `DictionaryTelemetry.build_key_fingerprint()` | 12 | O(1) | SHA-256 fingerprint ключа |
| `DictionaryTelemetry._should_sample_debug()` | 8 | O(1) | Deterministic sampling check |

*n = число словарей, d = число словарей в metadata*

---

### Функция: `dictionary_backend_resource()`

**Расположение**: `connector/delivery/cli/dictionaries_container.py:169`

**Сигнатура**:
```python
def dictionary_backend_resource(
    *,
    dsl_runtime_bundle: DictionaryDslRuntimeBundle | None,
    csv_loader: CsvDictionaryLoader,
    settings: DictionaryConfig,
    telemetry: DictionaryTelemetry,
) -> Iterator[PolarsDictionaryBackend | None]:
    """
    Resource-генератор backend словарей: init runtime state → eager/lazy policy → yield → no-op teardown.
    """
```

**Назначение**: Центральный orchestrator lifecycle backend словарей — здесь принимается решение о стратегии загрузки и инициализируется весь runtime.

**Алгоритм**:
```
1. Check disabled mode (lines 188-195)
   IF dsl_runtime_bundle IS None:
     telemetry.record_runtime_initialized(enabled=False, ...)
     yield None
     RETURN  (teardown no-op)

2. Create backend (line 197)
   backend = PolarsDictionaryBackend(bundle=dsl_runtime_bundle)

3. Record runtime init (lines 198-202)
   telemetry.record_runtime_initialized(
       enabled=True,
       load_strategy=settings.load_strategy,
       declared_dict_names=backend.get_declared_dict_names(),
   )

4. Apply load strategy (lines 204-215)
   IF load_strategy == "eager":
     csv_loader.load_into(backend)      # Загрузить все сразу (fail-fast)
   ELIF load_strategy == "lazy":
     backend.set_lazy_loader(            # Загружать по первому обращению
         lambda dict_name: csv_loader.load_dictionary_into(backend, dict_name=dict_name)
     )
   ELSE:
     RAISE DslLoadError(DICT_RUNTIME_INIT_FAILED, "Unsupported load_strategy")

5. yield backend  (line 216)
   (контейнер использует backend через lifecycle)

# teardown: нет явных действий (in-memory read-only)
```

**Инварианты**:
1. `yield None` — только при disabled mode (`dsl_runtime_bundle is None`)
2. Telemetry всегда вызывается (`record_runtime_initialized`) — даже при disabled
3. `load_strategy` должен быть `"eager"` или `"lazy"` — иначе `DslLoadError`
4. Ошибки загрузки при eager mode пробрасываются как `DslLoadError` (fail-fast)

**Edge cases**:
- **Пустой bundle** (`items: {}` / all disabled): backend создаётся, но `is_empty_runtime()=True`. Не загружается ничего ни при eager, ни при lazy.
- **Lazy + ошибка при первом lookup**: Ошибка пробрасывается через `_load_dictionary_lazy_if_needed()` без подавления.

---

### Функция: `_load_runtime_bundle_optional()`

**Расположение**: `connector/delivery/cli/dictionaries_container.py:49`

**Сигнатура**:
```python
def _load_runtime_bundle_optional(
    *,
    datasets_root: str | Path | None,
) -> DictionaryDslRuntimeBundle | None:
    """
    Собрать optional DSL runtime bundle словарей (без CSV IO).
    None возвращается только для disabled-mode (секция 'dictionaries' absent).
    """
```

**Назначение**: Склейка DSL-слоя с Core-слоем — загрузка YAML + компиляция в bundle, с поддержкой optional mode и кастомного `datasets_root`.

**Алгоритм**:
```
1. Active registry path (datasets_root is None) (lines 65-70)
   registry = load_optional_dictionary_registry_spec_for_runtime()
   IF registry IS None:
     RETURN None  ← disabled mode

   specs = load_enabled_dictionary_specs_for_runtime()
   manifest = load_dictionary_manifest_spec_for_runtime()
   RETURN build_dictionary_dsl_runtime(specs, manifest)

2. Custom datasets root (datasets_root is not None) — для тестов / fixtures (lines 72-79)
   registry_path = root / "registry.yml"
   IF NOT _has_dictionaries_section_or_raise(registry_path):
     RETURN None  ← disabled mode

   registry = load_dictionary_registry_spec(registry_path)
   specs = _load_enabled_specs_from_registry(registry, root)
   manifest = load_dictionary_manifest_spec(root / "dictionaries" / "manifest.yml")
   RETURN build_dictionary_dsl_runtime(specs, manifest)
```

**Ветка 1 (production/runtime)**: Использует активный registry path, уже настроенный DSL-loader'ом (`dataset.registry_path` или default `datasets/registry.yml`).

**Ветка 2 (tests)**: Использует кастомный `datasets_root` — позволяет изолировать тесты от production данных.

---

### Метод: `DictionaryTelemetry.build_key_fingerprint()`

**Расположение**: `connector/infra/dictionaries/telemetry.py:97`

**Сигнатура**:
```python
def build_key_fingerprint(self, normalized_key: Any) -> str:
    """
    Построить безопасный fingerprint ключа для логов/telemetry.
    Использует SHA-256(salt + normalized_key_text).
    Возвращает только короткий hex-prefix.
    Salt нигде не логируется.
    """
```

**Алгоритм**:
```
value_text = "" if normalized_key is None else str(normalized_key)
payload = (salt + value_text).encode("utf-8", errors="replace")
digest = hashlib.sha256(payload).hexdigest()
RETURN digest[:fingerprint_prefix_len]  # default: 12 chars

Пример с salt="mysalt", key="org-1":
payload = "mysaltorg-1".encode()
→ sha256("mysaltorg-1") = "a3f1c2..."
→ "a3f1c2d4e5f6" (12 chars)
```

**Зачем salt**: Без salt fingerprint = `sha256("org-1")` — предсказуем, brute-force-able для коротких значений. С salt — одноразовый fingerprint, не связанный с оригинальным ключом вне контекста одного deployment.

**Консистентность**: Fingerprint вычисляется от нормализованного ключа (после ops chain) — совпадает с тем, как ключ попадает в index. Это делает hit/miss fingerprints сравниваемыми.

---

### Метод: `DictionaryTelemetry.snapshot()`

**Расположение**: `connector/infra/dictionaries/telemetry.py:227`

**Назначение**: Вернуть сериализуемый snapshot всех counters и metadata для включения в report context.

**Структура результата**:
```python
{
    "component": "dictionary",
    "backend": "polars",
    "aggregate": {
        "lookup_total": 1500,
        "lookup_hit": 1200,
        "lookup_miss": 295,
        "lookup_error": 5,
    },
    "summary": {
        "runtime_enabled": True,
        "load_strategy": "eager",
        "declared_dictionaries": ["departments", "organizations"],
        "declared_count": 2,
        "loaded_count": 2,
        "warnings_count": 0,
    },
    "anomalies": [],
    "dictionaries_detail": {
        "organizations": {
            "lookup_total": 1200,
            "lookup_hit": 1000,
            "lookup_miss": 200,
            "lookup_error": 0,
            "row_count": 150,
            "fingerprint_kind": "content_sha256",
            "version_info": {
                "dict_name": "organizations",
                "version_id": "organizations:c797aaf53db7:59aff796321b",
                "schema_hash": "c797aaf53db754500bb427b7...",
                "row_count": 150,
                "source_format": "csv",
                "loaded_at": "2026-02-27T09:00:00Z",
                "fingerprint_kind": "content_sha256",
            },
            "anomalies": [],
        },
        ...
    }
}
```

**Lifecycle**: `snapshot()` вызывается в конце pipeline-прогона для включения в `report.context["dictionary"]`.

---

### Метод: `DictionaryTelemetry.record_lookup_result()`

**Расположение**: `connector/infra/dictionaries/telemetry.py:112`

**Алгоритм**:
```
1. Получить/создать per-dict counters (line 127)
   counters = _touch_counters(dict_name)

2. Инкрементировать counters (lines 128-129)
   _increment(counters, "lookup_total")  # aggregate + per_dict
   _increment(counters, "lookup_hit" if hit else "lookup_miss")

3. Deterministic sampling (lines 131-143)
   event = "lookup_hit" if hit else "lookup_miss"
   IF _should_sample_debug(event, dict_name, key_fingerprint):
     logger.debug(event,
       component="dictionary",
       dict_name=dict_name,
       op=op,
       backend=backend,
       key_fingerprint=key_fingerprint,  # ← только fingerprint, не plaintext key
       result_count=result_count,
       limit=limit,
       fields=list(fields) if fields else None,
     )
```

**Privacy-first логирование**: В structlog передаётся только `key_fingerprint` — 12-символьный hex. Plaintext ключ (например, `"john.doe@corp.com"`) никогда не попадает в логи.

---

## 🛠️ Как расширять

### Добавить новую стратегию загрузки (например, `"on-demand"`)

1. Добавить ветку в `dictionary_backend_resource()`:
   ```python
   elif load_strategy == "on-demand":
       # Загрузить только конкретные словари из конфига
       for dict_name in settings.preload_dictionaries:
           csv_loader.load_dictionary_into(backend, dict_name=dict_name)
       # Остальные — lazy
       backend.set_lazy_loader(...)
   ```

2. Добавить значение в `DictionaryConfig.load_strategy` (Pydantic enum/literal)

---

### Добавить новую метрику в telemetry

1. Добавить поле в `_LookupCounters`:
   ```python
   @dataclass
   class _LookupCounters:
       ...
       lookup_with_projection: int = 0  # ← новая метрика
   ```

2. Инкрементировать в `record_lookup_result()`:
   ```python
   if fields is not None:
       self._increment(counters, "lookup_with_projection")
   ```

3. Убедиться, что `_LookupCounters.as_dict()` возвращает новое поле

---

### Подключить DictionaryContainer к AppContainer

```python
# connector/delivery/cli/app_container.py
from connector.delivery.cli.dictionaries_container import DictionaryContainer

class AppContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    dictionary = providers.Container(
        DictionaryContainer,
        settings=config.dictionary,        # DictionaryConfig
        datasets_root=config.datasets_root,  # None → auto-detect
    )

    # В использующих контейнерах:
    enrich_engine = providers.Singleton(
        EnrichEngine,
        dict_provider=dictionary.provider,  # PolarsDictionaryProvider | None
    )
```

---

### Добавить report flush telemetry snapshot

```python
# В report collector или use case:
dictionary_snapshot = container.dictionary.telemetry().snapshot()
report.context["dictionary"] = dictionary_snapshot
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Dictionary DSL | Потребляет | `load_*_spec_for_runtime()` | Загрузка YAML конфигурации |
| Dictionary Core | Потребляет | `build_dictionary_dsl_runtime()` | Компиляция specs в bundle |
| Dictionary Infra (Backend) | Оркестрирует | `PolarsDictionaryBackend`, `CsvDictionaryLoader` | Создание и инициализация backend |
| Domain Ports | Реализует | `DictionaryProviderPort` | Provider реализует контракт |
| App Container | Предоставляет | `DictionaryContainer` | Монтируется как sub-container |
| Config | Потребляет | `DictionaryConfig` | Настройки fingerprint salt, sample percent, load strategy |
| Report | Предоставляет | `telemetry.snapshot()` | Snapshot counters для отчёта |

---

## 🔌 Контракты и границы

### DI-контракт: `DictionaryContainer`

**Входные зависимости** (должны быть инъецированы извне):
```python
settings = providers.Dependency(instance_of=DictionaryConfig)
datasets_root = providers.Dependency()  # str | Path | None
```

**Выходные зависимости** (предоставляет для AppContainer):
```python
provider  # PolarsDictionaryProvider | None
telemetry # DictionaryTelemetry (для report snapshot)
backend   # PolarsDictionaryBackend | None (при необходимости прямого доступа)
```

**Используется в**: `AppContainer` (composition root)

---

### Provider-контракт: `PolarsDictionaryProvider`

**Реализует**: `DictionaryProviderPort` (structural Protocol)

**Контракт методов**:

```python
# lookup: поиск по ключу → список совпадающих строк
rows = provider.lookup("organizations", " ORG-1 ", fields=("name",), limit=5)
# → [{"name": "Org One"}]        (hit, limit=5 → вернёт ≤5 результатов)
# → []                           (miss, нет совпадения)
# → []                           (empty runtime — disabled mode)

# contains: проверка существования ключа
ok = provider.contains("organizations", "ORG-1")
# → True / False
# → False                        (empty runtime)

# canonicalize: алиас для lookup без projection
rows = provider.canonicalize("organizations", "ORG-1")
# → [{"code": "ORG-1", "name": "Org One", "ouid": "100"}]
```

**Гарантии**:
- Никогда не возвращает `None` — только `[]`/`False`/`list`
- Никогда не подавляет ошибки backend — они пробрасываются после записи в telemetry
- Telemetry всегда обновляется — даже при empty runtime

---

### Telemetry-контракт: `DictionaryTelemetry`

**Порядок вызовов**:
```
1. record_runtime_initialized()  ← при init backend Resource
2. record_dictionary_loaded()    ← при загрузке каждого CSV (via callback)
3. record_lookup_result()        ← при каждом успешном lookup/contains/canonicalize
   OR record_lookup_error()      ← при ошибке
4. snapshot()                    ← в конце pipeline для report
```

**Инварианты**:
- `record_runtime_initialized()` вызывается ровно один раз
- `record_dictionary_loaded()` вызывается для каждого загруженного словаря
- `build_key_fingerprint()` может вызываться независимо от порядка

---

### Конфигурация: `DictionaryConfig`

**Поля** (Pydantic Settings):

| Поле | Тип | Default | Назначение |
|------|-----|---------|-----------|
| `load_strategy` | `str` | `"eager"` | Стратегия загрузки: `"eager"` или `"lazy"` |
| `fingerprint_salt` | `str` | — | Соль для SHA-256 fingerprinting lookup-ключей |
| `fingerprint_salt_version` | `str` | `"v1"` | Зарезервировано для ротации salt |
| `lookup_hit_sample_percent` | `int` | `1` | % hit-событий для debug log [0–100] |
| `lookup_miss_sample_percent` | `int` | `10` | % miss-событий для debug log [0–100] |

---

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `provider.py` → `connector/domain/ports/transform/dictionaries` — реализация порта
- ✅ `provider.py` → `connector/infra/dictionaries/backends/polars_backend` — backend
- ✅ `provider.py` → `connector/infra/dictionaries/telemetry` — telemetry
- ✅ `telemetry.py` → `connector/infra/dictionaries/loader_csv` — `DictionaryCsvLoadEvent`
- ✅ `telemetry.py` → `structlog`, `hashlib` — stdlib + structlog
- ✅ `dictionaries_container.py` → все infra/domain словарные модули — точка сборки
- ✅ `dictionaries_container.py` → `dependency_injector` — DI framework
- ✅ `dictionaries_container.py` → `connector/config/models.DictionaryConfig` — settings

**Запрещённые зависимости**:
- ❌ `provider.py` / `telemetry.py` → `connector/delivery/*` — не знают о DI
- ❌ `provider.py` → `connector/infra/dictionaries/loader_csv` — провайдер не работает с IO
- ❌ `telemetry.py` → `connector/infra/dictionaries/backends/*` — telemetry не знает о backend
- ❌ `dictionaries_container.py` → stage-specific code (enrich, import-plan) — только конфигурирует

**Визуальная граница**:
```
┌────────────────────────────────────────────────────────────────────┐
│ Delivery: DictionaryContainer (dictionaries_container.py)          │
│   - Composition: собирает object graph                              │
│   - Lifecycle: eager/lazy policy, init_resources()                 │
│   - Disabled mode: graceful None propagation                       │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ создаёт и конфигурирует
┌──────────────────▼─────────────────────────────────────────────────┐
│ Infra: PolarsDictionaryProvider (provider.py)                       │
│   - Implements: DictionaryProviderPort (Protocol)                   │
│   - Delegates: backend.lookup/contains/canonicalize                 │
│   - Wraps: telemetry on every call                                  │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ records events
┌──────────────────▼─────────────────────────────────────────────────┐
│ Infra: DictionaryTelemetry (telemetry.py)                           │
│   - Observability: counters, structlog, key fingerprinting          │
│   - Privacy: только fingerprint в логах, никогда plaintext          │
│   - Snapshot: сериализуемый dict для report context                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Полный startup с eager загрузкой

**Задача**: Запустить приложение с eager-загрузкой всех словарей.

**Конфигурация** (активный registry file):
```yaml
dictionaries:
  version: 1
  items:
    organizations:
      spec: dictionaries/organizations.dictionary.yaml
      enabled: true
```

**DI lifecycle**:
```python
# AppContainer монтирует DictionaryContainer
app_container.dictionary.init_resources()

# Внутри dictionary_backend_resource():
# 1. _load_runtime_bundle_optional() → DictionaryDslRuntimeBundle
# 2. PolarsDictionaryBackend(bundle=bundle)
# 3. telemetry.record_runtime_initialized(enabled=True, ...)
# 4. csv_loader.load_into(backend)
#    → Читает CSV, верифицирует fingerprints, строит key_index
#    → telemetry.record_dictionary_loaded(event)
# 5. yield backend

provider = app_container.dictionary.provider()
# → PolarsDictionaryProvider(backend, telemetry)

rows = provider.lookup("organizations", "ORG-1")
# → [{"code": "ORG-1", "name": "Org One", "ouid": "100"}]
```

---

### Сценарий 2: Graceful disabled mode

**Задача**: Задеплоить приложение на среду без словарных данных.

**Конфигурация**: Убрать секцию `dictionaries` из активного registry-файла.

**Поведение**:
```python
# _load_runtime_bundle_optional() → None (секция absent)
# dictionary_backend_resource() → yield None
# _build_provider_or_none(None, telemetry) → None

provider = app_container.dictionary.provider()  # → None

# EnrichEngine должен обрабатывать None provider:
if provider is not None:
    rows = provider.lookup("organizations", code)
else:
    rows = []

# telemetry.snapshot() → {"summary": {"runtime_enabled": False, ...}}
```

---

### Сценарий 3: Lookup с telemetry

**Задача**: Проследить путь одного lookup через все слои с telemetry.

**Поток**:
```
provider.lookup("organizations", " ORG-1 ", fields=("name",))

1. _safe_key_fingerprint("organizations", " ORG-1 ")
   → compiled.normalize_key(" ORG-1 ") = "org-1"
   → telemetry.build_key_fingerprint("org-1")
   → sha256(salt + "org-1")[:12] = "a3f1c2d4e5f6"

2. backend.lookup("organizations", " ORG-1 ", fields=("name",))
   → normalize " ORG-1 " → "org-1"
   → key_index["v:org-1"] = (0,)
   → rows[0] = {"code": "ORG-1", "name": "Org One", "ouid": "100"}
   → project {"name": "Org One"}
   → return [{"name": "Org One"}]

3. telemetry.record_lookup_result(
       dict_name="organizations", op="lookup",
       hit=True, key_fingerprint="a3f1c2d4e5f6",
       result_count=1, limit=None, fields=("name",)
   )
   → _aggregate.lookup_total += 1
   → _aggregate.lookup_hit += 1
   → per_dict["organizations"].lookup_hit += 1
   → IF _should_sample_debug("lookup_hit", "organizations", "a3f1c2d4e5f6"):
       logger.debug("lookup_hit", component="dictionary",
                    dict_name="organizations", key_fingerprint="a3f1c2d4e5f6", ...)

4. return [{"name": "Org One"}]
```

---

### Сценарий 4: Обнаружение anomaly (пустой словарь)

**Задача**: CSV-файл существует и валиден по fingerprint, но содержит 0 строк.

**Поведение при загрузке**:
```
csv_loader.load_dictionary_into(backend, dict_name="organizations")
→ frame.height == 0 == manifest.row_count  ← fingerprint OK
→ backend.load_dictionary_frame(...)       ← загрузка пустого DataFrame
→ _emit_load_event(DictionaryCsvLoadEvent(row_count=0, source_empty=True, ...))

telemetry.record_dictionary_loaded(event)
→ meta.row_count = 0
→ meta.anomalies.append({
    "code": "DICT_SOURCE_EMPTY",
    "severity": "WARNING",
    "dict_name": "organizations",
    "row_count": 0,
    ...
  })
→ logger.warning("source_empty", component="dictionary", ...)

telemetry.snapshot()["anomalies"]
→ [{"code": "DICT_SOURCE_EMPTY", "severity": "WARNING", ...}]
```

**Поведение при lookup**: `lookup()` возвращает `[]` — не ошибка, просто пустой результат.

---

### Сценарий 5: Мониторинг через snapshot

**Задача**: Включить статистику словарей в итоговый отчёт pipeline.

**Решение**:
```python
# В pipeline report collector:
telemetry = app_container.dictionary.telemetry()
report.context["dictionary"] = telemetry.snapshot()

# Итоговый отчёт содержит:
# {
#   "dictionary": {
#     "aggregate": {"lookup_total": 500, "lookup_hit": 450, "lookup_miss": 50},
#     "summary": {"runtime_enabled": True, "loaded_count": 2, "warnings_count": 0},
#     "dictionaries_detail": {
#       "organizations": {"lookup_hit": 300, "row_count": 150, ...},
#       "departments": {"lookup_hit": 150, "row_count": 20, ...},
#     }
#   }
# }
```

---

## 📌 Важные детали

### Особенности реализации

- **`provider = None` при disabled mode**: Это явный null, не Null Object. Consumers (EnrichEngine) должны явно обрабатывать `None`. Это сделано намеренно — чтобы disabled mode был виден в коде, а не скрыт за пустым объектом.

- **`telemetry.record_runtime_initialized()` всегда вызывается**: Даже при disabled mode — это обеспечивает полный snapshot даже если словари выключены.

- **`_safe_key_fingerprint()` — defensive**: При любой ошибке нормализации используется raw value для fingerprinting. Это не меняет бизнес-поведение lookup, но гарантирует что telemetry всегда получит fingerprint.

- **Sampling настраивается в `DictionaryConfig`**: `lookup_hit_sample_percent=1` означает ~1% hit-событий попадут в debug log. При `0` — логирование выключено, при `100` — все события.

- **`fingerprint_salt_version`**: Зарезервировано для ротации salt. При изменении salt fingerprints меняются — это нормально, т.к. fingerprint нужен только в рамках одного deployment для корреляции в логах.

- **Telemetry не является метрикой Prometheus**: Это in-process counters для pipeline report. Для production мониторинга нужно дополнительно экспортировать `snapshot()` в систему метрик.

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError(DICT_RUNTIME_INIT_FAILED)` | Неизвестный `load_strategy` в `DictionaryConfig` | Fail-fast при `container.init_resources()` | Установить `load_strategy: "eager"` или `"lazy"` |
| `DslLoadError(*)` при eager | Любая ошибка CSV/fingerprint/schema при eager загрузке | Fail-fast при `init_resources()` | Исправить CSV данные или manifest |
| `DslLoadError(*)` при lazy | Любая ошибка при первом lookup в lazy режиме | Ошибка пробрасывается из `lookup()` | Исправить CSV данные — ошибка воспроизводима |
| `ValueError` в `DictionaryTelemetry.__init__` | `lookup_hit_sample_percent` или `lookup_miss_sample_percent` вне [0, 100] | Fail-fast при создании telemetry | Исправить значения в `DictionaryConfig` |
| `RuntimeError` — recursive lazy | Lazy loader вызвал lookup по тому же словарю | Исключение в backend | Устранить рекурсию в init логике |

### ⚠️ Инварианты системы

1. **Инвариант: Telemetry всегда инициализирована**
   - **Что**: `record_runtime_initialized()` вызывается ровно один раз в `dictionary_backend_resource()`
   - **Почему важно**: Snapshot без `record_runtime_initialized()` не будет содержать summary
   - **Где проверяется**: `dictionary_backend_resource()` lines 189–202

2. **Инвариант: Provider None ↔ Backend None**
   - **Что**: `_build_provider_or_none(backend=None)` всегда возвращает `None`; при ненулевом backend — всегда возвращает Provider
   - **Почему важно**: Consumers проверяют `if provider is not None` — несоответствие сломало бы disabled mode
   - **Где проверяется**: `_build_provider_or_none()` в `dictionaries_container.py:219`

3. **Инвариант: Telemetry получает fingerprint, не plaintext**
   - **Что**: В `record_lookup_result/error()` передаётся только `key_fingerprint` (12-hex)
   - **Почему важно**: Sensitive lookup keys (email, personnel id) не должны попадать в логи
   - **Где проверяется**: `PolarsDictionaryProvider._safe_key_fingerprint()` перед каждым вызовом

4. **Инвариант: Counters aggregate = sum per-dict**
   - **Что**: `_aggregate.lookup_total == sum(c.lookup_total for c in _per_dictionary.values())`
   - **Почему важно**: Aggregate должен отражать реальный total для отчётов
   - **Где проверяется**: `_increment()` всегда обновляет оба — aggregate и per-dict

### ⏱️ Performance заметки

**Узкие места**:

1. **Eager startup при большом числе словарей**
   - **Проблема**: Все CSV читаются последовательно при `init_resources()`
   - **Текущая оптимизация**: Нет; v2 может добавить параллельную загрузку
   - **Mitigation**: Использовать `lazy` strategy если быстрый старт критичен

2. **SHA-256 в `build_key_fingerprint()`**
   - **Проблема**: Вызывается при каждом lookup для telemetry
   - **Текущая оптимизация**: SHA-256 — ~0.2 мкс, приемлемо для большинства use cases
   - **Если критично**: Увеличить `lookup_hit_sample_percent=0` для отключения loggi-ng, fingerprint всё равно вычисляется

3. **Sampling hash в `_sample_bucket()`**
   - **Проблема**: Ещё один SHA-256 для решения о sampling
   - **Текущая оптимизация**: Вычисляется только если `percent > 0`

**Оптимизации**:
- **`lookup_hit_sample_percent=0`**: Полностью отключает debug logging для hit-событий
- **`lazy` mode**: Откладывает CSV загрузку до первого реального обращения

---

## 🔗 Связанные документы

- [Dictionary DSL](./dictionary-dsl.md) — Pydantic-модели, порт `DictionaryProviderPort`
- [Dictionary Core](./dictionary-core.md) — Runtime compilation, versioning
- [Dictionary Infra (Backend)](./dictionary-infra.md) — PolarsDictionaryBackend, CsvDictionaryLoader
- [ADR: Columnar Dictionary Runtime](../../adr/transform/TRANSFORM-DEC-001-columnar-dictionary-runtime-for-enricher.md)
- [Cache Delivery](../cache/cache-infra.md) — аналогичный паттерн delivery в cache-слое

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Первоначальное создание документа | xORex-LC |
| 2026-05-05 | Уточнён runtime flow словарей для active registry path и custom datasets root | xORex-LC |
