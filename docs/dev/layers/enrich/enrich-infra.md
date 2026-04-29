# Enrich Infra — порты, провайдеры и DI-wiring обогащения

> Инфраструктурный слой enrich изолирует `EnricherCore` от конкретных реализаций через три domain-порта, `ProviderGateway` с пятью встроенными провайдерами и `StageExecutionContext` с DI-wiring в `connector/delivery/`.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO](#️-how-to)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

Enrich-слой взаимодействует с тремя видами внешней инфраструктуры:

| Инфраструктура | Роль | Порт |
|----------------|------|------|
| **Cache** (SQLite) | Lookup по полю, проверка уникальности | `EnrichLookupPort` |
| **Dictionary** (CSV/Temporal) | Нормативные справочники, канонизация | `DictionaryProviderPort` |
| **Vault** (SQLite + Fernet) | Хранение секретов (паролей) | `SecretStoreProtocol` |

Ключевой принцип — **`EnricherCore` не знает ни о каком из этих бэкендов**.
Он получает только `deps: SimpleNamespace` с атрибутами `cache_gateway`, `dictionaries`,
`secret_store`, значения которых могут быть `None`.

Всё взаимодействие с инфраструктурой происходит через:
1. **Domain Protocols** (в `connector/domain/ports/`) — контракты без реализации
2. **ProviderGateway** (в `connector/domain/transform/providers/`) — мост от DSL-правил к портам
3. **StageExecutionContext** — scoped контейнер capabilities для одной стадии
4. **DI wiring** (только в `connector/delivery/`) — единственное место, где domain встречает infra

---

## 🏗️ Архитектура слоя

```
connector/domain/                      connector/infra/
├── ports/                             ├── cache/
│   ├── cache/roles.py                 │   └── cache_gateway.py ← реализует EnrichLookupPort
│   │   └── EnrichLookupPort ──────────┤   └── roles.py         ← SqliteCacheRolePorts.enrich_lookup
│   ├── transform/dictionaries.py      ├── secrets/
│   │   └── DictionaryProviderPort     │   ├── sqlite/          ← SqliteVaultRepository
│   └── secrets/provider.py            └── (SecretVaultWriteService в domain/secrets/)
│       └── SecretStoreProtocol
│
├── transform/
│   ├── providers/
│   │   └── registry.py  ← ProviderGateway (bridge: port → DSL provider name)
│   └── enrich/
│       ├── enricher_engine.py ← SimpleNamespace deps (НЕ импортирует infra)
│       └── enricher_core.py   ← deps.cache_gateway / deps.dictionaries (getattr)
│
└── secrets/
    └── secret_vault_write_service.py ← SecretVaultWriteService implements SecretStoreProtocol

connector/delivery/
├── commands/enrich.py     ← vault решение (_dataset_requires_vault)
└── cli/containers.py      ← _build_enrich_context() (единственный DI-wiring)
    ├── PipelineContainer.enrich_context
    └── PipelineContainer.enrich_stage
```

**Правило:** ни один файл в `connector/domain/transform/enrich/` не импортирует из
`connector/infra/` напрямую. Зависимость всегда идёт через Protocol.

---

## 🔑 Ключевые абстракции

### EnrichLookupPort — доступ к кэшу

**Файл:** `connector/domain/ports/cache/roles.py`

```python
class EnrichLookupPort(Protocol):
    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]: ...

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None: ...
```

| Параметр | Тип | Описание |
|----------|-----|---------|
| `dataset` | `str` | Имя датасета в кэше (напр. `"employees"`) |
| `filters` | `dict` | Критерии поиска `{field: value}` |
| `include_deleted` | `bool` | Включать удалённые записи (default `False`) |
| `mode` | `str` | Режим сравнения: `"exact"` или `"fuzzy"` |

**Реализация:** `SqliteCacheGateway` из `connector/infra/cache/cache_gateway.py`.
В production порт предоставляется через `SqliteCacheRolePorts.enrich_lookup` (специализированная
«роль» с ограниченным интерфейсом — только `find` и `find_one`, без admin-операций).

**Обязательность:** `EnrichLookupPort` — **обязательная** capability для EnrichStage.
Без неё провайдеры `cache.by_field` и `cache.exists_by_field` упадут с `AttributeError`.

### DictionaryProviderPort — доступ к справочникам

**Файл:** `connector/domain/ports/transform/dictionaries.py`

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

| Метод | Возвращает | Провайдер |
|-------|-----------|-----------|
| `lookup()` | `list[dict]` | `dictionary.by_key` — поиск по точному ключу |
| `contains()` | `bool` | (зарезервирован, в enrich не используется) |
| `canonicalize()` | `list[dict]` | `dictionary.canonicalize` — нормализация к каноническому значению |

**Реализация:** `DictionaryRuntime` из `connector/delivery/cli/dictionaries_container.py`.
DictionaryContainer создаёт runtime, работающий с CSV/Polars бэкендом.

**Опциональность:** если `DictionaryProviderPort` не зарегистрирован, `deps.dictionaries = None`,
и провайдеры `dictionary.*` упадут с `AttributeError` при первом вызове.

### SecretStoreProtocol — запись секретов в Vault

**Файл:** `connector/domain/ports/secrets/provider.py`

```python
class SecretStoreProtocol(Protocol):
    def put_many(
        self,
        *,
        dataset: str,
        match_key: str,
        secrets: dict[str, str],
        run_id: str | None = None,
    ) -> None: ...
```

**Семантика `put_many()`:**
- `dataset` — имя датасета (`"employees"`)
- `match_key` — уникальный идентификатор записи (`"Doe|John|Иванович|u-001"`)
- `secrets` — `{field_name: plaintext_value}` — секреты в открытом виде
- `run_id` — идентификатор запуска (для audit trail)

**Реализация:** `SecretVaultWriteService` из `connector/domain/secrets/secret_vault_write_service.py`.
Шифрует значения через `FernetEnvelopeCipher` перед записью в `SqliteVaultRepository`.

**Опциональность:** если `SecretStoreProtocol` не передан (`secret_store = None`),
секреты не записываются в vault. `_store_secrets()` всё равно очищает `row[field] = None`
и заполняет `meta["secret_fields"]`. Используется при `--vault-mode=off`.

### CandidateProvider Protocol

**Файл:** `connector/domain/transform/enrich/providers.py`

```python
class CandidateProvider(Protocol, Generic[T, D]):
    name: str

    def fetch(
        self,
        ctx: EnrichContext,
        result: TransformResult[T],
        deps: D,
        key_values: dict[str, Any],
    ) -> list[CandidateValue]: ...
```

Низкоуровневый контракт для runtime lookup-провайдеров. `_DslLookupProvider`
из `compilers/enrich.py` реализует его, делегируя в `ProviderGateway`.

---

## 🗂️ Модели данных

### PipelineMetadata

**Файл:** `connector/domain/transform/context.py`

```python
@dataclass(frozen=True)
class PipelineMetadata:
    run_id: str                    # уникальный ID запуска
    dataset_name: str              # "employees"
    catalog: ErrorCatalog          # диагностический каталог
    sink_spec: SinkSpec | None     # sink-схема для валидации
```

Иммутабельные метаданные запуска — общие для всех стадий pipeline.

### MissingCapabilityError

**Файл:** `connector/domain/transform/context.py`

```python
class MissingCapabilityError(Exception):
    def __init__(self, port_type: type, available: list[type]) -> None:
        available_names = [t.__name__ for t in available]
        super().__init__(
            f"Capability {port_type.__name__} is not available. "
            f"Registered: {available_names}"
        )
```

Выбрасывается `StageExecutionContext.require()` при запросе незарегистрированной capability.

### LookupProvider и ExistsProvider

**Файл:** `connector/domain/transform/providers/registry.py`

```python
LookupProvider = Callable[[Any, Any], list[dict[str, Any]]]
ExistsProvider = Callable[[Any, Any], Any | None]
```

Type aliases для функций-провайдеров. Подпись: `(deps, value, *, args) -> result`.

---

## 📊 Ключевые методы и алгоритмы

### `StageExecutionContext` — scoped capabilities

**Файл:** `connector/domain/transform/context.py`

```python
class StageExecutionContext:
    def __init__(
        self,
        metadata: PipelineMetadata,
        capabilities: dict[type, object],
    ) -> None:
        self._metadata = metadata
        self._capabilities = dict(capabilities)   # defensive copy

    @property
    def metadata(self) -> PipelineMetadata: ...

    def get(self, port_type: type[T]) -> T | None:
        """Мягкий доступ — None если capability отсутствует."""
        return self._capabilities.get(port_type)

    def require(self, port_type: type[T]) -> T:
        """Жёсткий доступ — raises MissingCapabilityError."""
        instance = self._capabilities.get(port_type)
        if instance is None:
            raise MissingCapabilityError(
                port_type=port_type,
                available=list(self._capabilities.keys()),
            )
        return instance

    def has(self, port_type: type) -> bool:
        return port_type in self._capabilities
```

`EnricherEngine` использует `.get()` для всех трёх портов — отсутствие опциональных портов
не является ошибкой инициализации.

### `ProviderGateway` — реестр провайдеров

**Файл:** `connector/domain/transform/providers/registry.py`

```python
@dataclass
class ProviderGateway:
    _lookup: dict[str, LookupProvider] = field(default_factory=dict)
    _exists: dict[str, ExistsProvider] = field(default_factory=dict)

    @classmethod
    def with_defaults(cls) -> "ProviderGateway":
        registry = cls()
        registry.register_lookup("cache.by_field", _cache_by_field)
        registry.register_exists("cache.exists_by_field", _cache_exists_by_field)
        registry.register_lookup("dictionary.by_key", _dictionary_by_key)
        registry.register_lookup("dictionary.canonicalize", _dictionary_canonicalize)
        registry.register_exists("dictionary.exists_by_key", _dictionary_exists_by_key)
        return registry

    def lookup(self, name: str, deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict]:
        provider = self._lookup.get(name)
        if provider is None:
            raise KeyError(f"Unknown lookup provider: {name}")
        return provider(deps, value, args=args)

    def exists(self, name: str, deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
        provider = self._exists.get(name)
        if provider is None:
            raise KeyError(f"Unknown exists provider: {name}")
        return provider(deps, value, args=args)
```

**Полная таблица 5 встроенных провайдеров:**

| Имя | Тип | Порт | Метод | Обязательные args | Опциональные args |
|-----|-----|------|-------|-------------------|------------------|
| `cache.by_field` | lookup | `EnrichLookupPort` | `find()` | `dataset`, `field` | `include_deleted`, `mode` |
| `cache.exists_by_field` | exists | `EnrichLookupPort` | `find_one()` | `dataset`, `field` | `include_deleted`, `mode` |
| `dictionary.by_key` | lookup | `DictionaryProviderPort` | `lookup()` | `dict_name` | `at`, `fields`, `limit` |
| `dictionary.canonicalize` | lookup | `DictionaryProviderPort` | `canonicalize()` | `dict_name` | `at`, `limit` |
| `dictionary.exists_by_key` | exists | `DictionaryProviderPort` | `lookup(limit=1)` | `dict_name` | `at`, `fields` |

### Детали реализации: cache провайдеры

```python
def _cache_by_field(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict]:
    cache_gateway = getattr(deps, "cache_gateway", None)
    if cache_gateway is None:
        raise AttributeError("deps.cache_gateway is required for provider 'cache.by_field'")
    dataset = str(args["dataset"])
    field = str(args["field"])
    include_deleted = bool(args.get("include_deleted", False))
    mode = str(args.get("mode", "exact"))
    return cache_gateway.find(dataset, {field: value},
                               include_deleted=include_deleted, mode=mode)


def _cache_exists_by_field(deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
    # Возвращает dict | None (не bool!) — allow_if работает с полями existing
    return cache_gateway.find_one(dataset, {field: value},
                                   include_deleted=include_deleted, mode=mode)
```

**Важно:** `exists`-провайдеры обязаны возвращать `row | None`, не `bool` — потому что
`allow_if()` получает `existing` и работает с его полями (`existing["match_key"]`).

### Детали реализации: dictionary провайдеры

```python
def _dictionary_by_key(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict]:
    dictionaries = _require_dictionaries(deps, ...)  # getattr(deps, "dictionaries", None)
    dict_name, at, fields, limit = _extract_dictionary_lookup_args(args, ...)
    # Валидация: только {"dict_name", "at", "fields", "limit"} — лишние → ValueError
    # fields: list/tuple → TypeError если нет; limit: > 0 → ValueError
    return dictionaries.lookup(dict_name, str(value), at=at, fields=fields, limit=limit)


def _dictionary_exists_by_key(deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
    rows = dictionaries.lookup(dict_name, str(value), at=at, fields=fields, limit=1)
    return rows[0] if rows else None   # dict | None
```

### `_build_enrich_context()` — DI wiring

**Файл:** `connector/delivery/cli/containers.py`

```python
def _build_enrich_context(
    metadata: PipelineMetadata,
    cache_roles: SqliteCacheRolePorts,
    secret_store: object | None,
    dictionaries: object | None,
) -> StageExecutionContext:
    caps: dict[type, object] = {
        EnrichLookupPort: cache_roles.enrich_lookup   # ОБЯЗАТЕЛЬНО
    }
    if secret_store is not None:
        caps[SecretStoreProtocol] = secret_store      # опционально
    if dictionaries is not None:
        caps[DictionaryProviderPort] = dictionaries   # опционально
    return StageExecutionContext(metadata=metadata, capabilities=caps)
```

**Capabilities enrich-стадии:**

| Port type | В `_build_enrich_context()` | Когда None |
|-----------|---------------------------|-----------|
| `EnrichLookupPort` | **Всегда** добавляется | Никогда (обязателен) |
| `SecretStoreProtocol` | Только если vault enabled | `--vault-mode=off` или нет secret fields |
| `DictionaryProviderPort` | Только если dictionaries init | `--no-dictionaries` или нет бэкенда |

### `_dataset_requires_vault()` — условная инициализация Vault

**Файл:** `connector/delivery/commands/enrich.py`

```python
def _dataset_requires_vault(dataset_spec) -> bool:
    enrich_spec = dataset_spec.build_enrich_spec()

    secrets = enrich_spec.enrich.secrets
    if secrets is not None:
        for field in secrets.fields:
            if isinstance(field, str) and field.strip():
                return True

    for rule in (*enrich_spec.enrich.generate, *enrich_spec.enrich.lookup):
        target = str(rule.target or "").strip()
        if target.startswith("secret:"):
            return True

    return False
```

**Полный flow принятия решения о Vault:**

```
1. _dataset_requires_vault(spec) → True/False

2. resolve_vault_runtime_mode(mode=opts.vault_mode, requires_vault=True/False)
   → mode: "auto" | "on" | "off"

3. Валидация:
   - mode="off" и requires_vault=True → ERROR

4. evaluate_vault_rollout(settings, ...) → rollout_decision.vault_enabled

5. if rollout_decision.vault_enabled:
       vault_ready.init()
       secret_store = vault.write_service()   # SecretVaultWriteService
   else:
       secret_store = None

6. pipeline.secret_store.override(secret_store)
```

---

## 🔄 Взаимодействие с другими слоями

### AppContainer sub-containers

```
AppContainer
├── sqlite          ← SqliteContainer: 3 SQLite engines (cache/vault/identity)
│   ├── cache_engine    → CacheContainer.gateway → SqliteCacheGateway → EnrichLookupPort
│   └── vault_engine    → VaultContainer.write_service → SecretVaultWriteService → SecretStoreProtocol
├── cache           ← CacheContainer
│   └── roles           → SqliteCacheRolePorts
│       └── enrich_lookup  ← implements EnrichLookupPort
├── vault           ← VaultContainer
│   ├── cipher          ← FernetEnvelopeCipher (шифрование)
│   ├── key_provider    ← UnsealedVaultKeyProvider (ключ из runtime unseal passphrase)
│   └── write_service   ← SecretVaultWriteService implements SecretStoreProtocol
├── dictionary      ← DictionaryContainer
│   ├── backend         ← Resource (ленивая инициализация CSV/Polars)
│   └── provider        ← DictionaryRuntime implements DictionaryProviderPort
└── pipeline        ← PipelineContainer
    ├── enrich_context  ← _build_enrich_context(metadata, cache_roles, secret_store, dicts)
    └── enrich_stage    ← EnricherEngine(spec, ctx=enrich_context)
```

### PipelineContainer wiring

```python
class PipelineContainer(containers.DeclarativeContainer):
    cache_roles   = providers.Dependency(instance_of=object)
    secret_store  = providers.Object(None)    # дефолт None
    dictionaries  = providers.Object(None)    # дефолт None

    pipeline_metadata = providers.Factory(PipelineMetadata, ...)

    enrich_context = providers.Factory(
        _build_enrich_context,
        metadata=pipeline_metadata,
        cache_roles=cache_roles,
        secret_store=secret_store,
        dictionaries=dictionaries,
    )

    enrich_stage = providers.Factory(
        _create_stage,
        stage_type="enrich",
        ctx=enrich_context,
        ...
    )
```

### SimpleNamespace deps — граница domain/infra внутри domain

```python
# enricher_engine.py — создаётся при ctx-пути:
from types import SimpleNamespace

effective_deps = SimpleNamespace(
    cache_gateway=ctx.get(EnrichLookupPort),       # EnrichLookupPort | None
    secret_store=ctx.get(SecretStoreProtocol),     # SecretStoreProtocol | None
    dictionaries=ctx.get(DictionaryProviderPort),  # DictionaryProviderPort | None
)
```

`SimpleNamespace` — обычный Python-объект с атрибутами. Создаётся внутри `connector/domain/`
и никогда не содержит прямых ссылок на инфра-классы (только Protocol-совместимые объекты).

Все провайдеры в `registry.py` читают deps через `getattr` с дефолтом `None`:

```python
cache_gateway = getattr(deps, "cache_gateway", None)
dictionaries  = getattr(deps, "dictionaries", None)
```

Это упрощает написание тестовых stub-объектов без наследования от реальных классов.

---

## 🔌 Контракты и границы

**Enrich-infra пакет** содержит только:
- Domain ports в `connector/domain/ports/`
- `ProviderGateway` в `connector/domain/transform/providers/registry.py`
- `StageExecutionContext`, `PipelineMetadata` в `connector/domain/transform/context.py`

**Запрещённые импорты в `enricher_core.py` и `enricher_engine.py`:**
- `connector/infra/` — никакой инфраструктуры напрямую
- `connector/delivery/` — никакой доставки

**Правила изоляции:**

| ❌ Нарушение | ✅ Правильно |
|-------------|-------------|
| Импорт `SqliteCacheGateway` в `enricher_core.py` | Работать через `EnrichLookupPort` Protocol |
| Импорт `SqliteVaultRepository` в enrich | Работать через `SecretStoreProtocol` |
| Вызов `find_one()` напрямую в `EnricherCore` | Делать через `ProviderGateway → CandidateProvider` |
| Добавить новый провайдер в `enricher_core.py` | Зарегистрировать в `ProviderGateway.with_defaults()` |
| Создать `AppContainer()` внутри enrich | DI-wiring только в `connector/delivery/` |
| Хранить `StageExecutionContext` как поле класса | Распаковывать в `__init__` в `SimpleNamespace` |
| `if isinstance(deps.cache_gateway, SqliteCacheGateway)` | Использовать Protocol-контракт |

**Архитектурный принцип:**

```python
# ✅ Допустимо в connector/domain/transform/enrich/:
from connector.domain.ports.cache.roles import EnrichLookupPort
from connector.domain.ports.secrets.provider import SecretStoreProtocol

# ❌ Запрещено в connector/domain/transform/enrich/:
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.secrets.sqlite import SqliteVaultRepository
```

Единственное место, где `connector.domain` встречает `connector.infra`:
```
connector/delivery/cli/containers.py
connector/delivery/commands/enrich.py
```

---

## 🛠️ HOW-TO

### Добавить новый lookup-провайдер

1. Написать функцию-провайдер в `connector/domain/transform/providers/registry.py`:

```python
def _my_new_provider(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict]:
    my_service = getattr(deps, "my_service", None)
    if my_service is None:
        raise AttributeError("deps.my_service is required for provider 'my.provider'")
    param = str(args["param"])
    return my_service.search(value, param=param)
```

2. Зарегистрировать в `ProviderGateway.with_defaults()`:

```python
registry.register_lookup("my.provider", _my_new_provider)
```

3. Если нужен новый порт — создать Protocol в `connector/domain/ports/`:

```python
class MyServicePort(Protocol):
    def search(self, value: str, *, param: str) -> list[dict]: ...
```

4. Добавить атрибут в `SimpleNamespace` в `enricher_engine.py`:

```python
effective_deps = SimpleNamespace(
    cache_gateway=ctx.get(EnrichLookupPort),
    secret_store=ctx.get(SecretStoreProtocol),
    dictionaries=ctx.get(DictionaryProviderPort),
    my_service=ctx.get(MyServicePort),          # ← добавить
)
```

5. Добавить в `_build_enrich_context()` в `containers.py`:

```python
if my_service := ctx.get(MyServicePort):
    caps[MyServicePort] = my_service
```

---

### Тестировать без реальных инфраструктурных зависимостей

```python
from types import SimpleNamespace
from connector.domain.transform.context import StageExecutionContext, PipelineMetadata

class FakeCacheGateway:
    def find(self, dataset, filters, *, include_deleted=False, mode="exact"):
        return []
    def find_one(self, dataset, filters, *, include_deleted=False, mode="exact"):
        return None

class FakeSecretStore:
    def __init__(self):
        self.written = {}
    def put_many(self, *, dataset, match_key, secrets, run_id=None):
        self.written[match_key] = secrets

metadata = PipelineMetadata(
    run_id="test-run",
    dataset_name="employees",
    catalog=ErrorCatalog(dataset="employees", items={}),
)
ctx = StageExecutionContext(
    metadata=metadata,
    capabilities={
        EnrichLookupPort: FakeCacheGateway(),
        SecretStoreProtocol: FakeSecretStore(),
    },
)
engine = EnricherEngine(spec=enrich_spec, ctx=ctx)
```

---

### Подключить новый справочник (dictionary)

Словари доступны через `DictionaryProviderPort` без изменения кода enrich-слоя:

1. Создать DSL-файл справочника в `datasets/dicts/my_dict.yaml`
2. Зарегистрировать в `datasets/registry.yml` в секции `cache:`
3. Использовать в enrich DSL:

```yaml
lookup:
  - name: my_field_lookup
    target: my_field
    source: source_field
    provider:
      name: dictionary.by_key
      args:
        dict_name: my_dict
        fields: [canonical_value]
    on_error: warn
```

---

### Добавить новый инфра-бэкенд без нарушения изоляции

Например, заменить SQLite кэш на Redis:

1. Создать `connector/infra/cache/redis_gateway.py`, реализующий `EnrichLookupPort`
2. Создать новый Role класс в `connector/infra/cache/roles.py`
3. Добавить в `CacheContainer` в `containers.py`
4. Проброс через `_build_enrich_context()` — без изменений domain-кода

**Не нужно менять:** `enricher_core.py`, `enricher_engine.py`, `providers/registry.py`, DSL-файлы.

---

## 💡 Типичные сценарии

### Сценарий 1: Датасет без словарей и vault

```
_build_enrich_context():
  caps = {EnrichLookupPort: cache_roles.enrich_lookup}
  (secret_store=None, dictionaries=None)
  → StageExecutionContext с одной capability

EnricherEngine.__init__():
  effective_deps = SimpleNamespace(
      cache_gateway=FakeCacheGateway(),  # EnrichLookupPort
      secret_store=None,                 # vault выключен
      dictionaries=None,                 # нет справочников
  )

_store_secrets():
  secret_candidates пуст → ранний выход
```

---

### Сценарий 2: Vault активирован

```
_dataset_requires_vault(spec) → True (есть secrets.fields=[password])
evaluate_vault_rollout(...)   → vault_enabled=True

secret_store = vault.write_service()  # SecretVaultWriteService

pipeline.secret_store.override(secret_store)
→ enrich_context:
  caps = {
      EnrichLookupPort:    cache_roles.enrich_lookup,
      SecretStoreProtocol: SecretVaultWriteService(...),
  }

_store_secrets():
  secret_store.put_many(dataset="employees", match_key="Doe|...",
                          secrets={"password": "plaintext"})
  → FernetEnvelopeCipher.encrypt("plaintext") → base64-ciphertext
  → SqliteVaultRepository.upsert(dataset, match_key, {"password": encrypted})
```

---

### Сценарий 3: Отсутствующий справочник (AttributeError)

```
DSL: dictionary.by_key provider → deps.dictionaries is None

_dictionary_by_key(deps, "77", args={dict_name="positions"}):
  dictionaries = getattr(deps, "dictionaries", None)
  → None
  → raise AttributeError("deps.dictionaries is required for provider 'dictionary.by_key'")

EnricherCore._collect_candidates():
  op_error = _EnrichOpError(code="ENRICH_PROVIDER_ERROR", ...)
  → _report_by_policy(strictness.on_provider_error)
  → DiagnosticItem в errors или warnings
```

---

## 📌 Важные детали

| Деталь | Описание |
|--------|----------|
| `EnrichLookupPort` обязателен | `AttributeError` при любом cache-провайдере если не зарегистрирован |
| `exists`-провайдер возвращает `dict\|None` | Не `bool` — `allow_if()` работает с полями `existing` |
| `_build_enrich_context()` — единственный DI | Только здесь domain встречает infra; нигде больше |
| `StageExecutionContext` defensive copy | `capabilities = dict(capabilities)` при создании — нельзя изменить снаружи |
| `SimpleNamespace` — структурный тайпинг | `getattr(deps, "key", None)` вместо `isinstance` — легко мокать в тестах |
| Vault решение per-command | `_dataset_requires_vault()` вызывается каждый раз в `enrich` команде |
| `DictionaryProviderPort` опционален | Если нет правил с `dictionary.*` — `deps.dictionaries=None` не проблема |

**Что знает каждый компонент:**

| Компонент | Cache | Dictionary | Vault | Infra-классы |
|-----------|:-----:|:----------:|:-----:|:------------:|
| `enricher_core.py` | ❌ | ❌ | ✅ Protocol | ❌ |
| `enricher_engine.py` | ✅ Protocol | ✅ Protocol | ✅ Protocol | ❌ |
| `providers/registry.py` | ✅ getattr | ✅ getattr | ❌ | ❌ |
| `_build_enrich_context()` | ✅ | ✅ | ✅ | ✅ |

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_enricher.py` | EnricherCore + stub deps (FakeCacheGateway) |
| `tests/integration/secrets/test_enrich_vault_write_service.py` | Vault write с шифрованием |
| `tests/integration/delivery/test_pipeline_container.py` | DI wiring enrich stage |
| `tests/e2e/pipelines/test_enrich_pipeline.py` | Полный pipeline с реальными зависимостями |
| `tests/unit/transform/test_enrich_dsl.py` | Provider args validation, template expansion |

---

## ❓ FAQ

**Почему deps это SimpleNamespace, а не TypedDict или dataclass?**

`SimpleNamespace` создаётся в domain без знания об инфра-классах — только Protocol-совместимые объекты.
Лёгкость создания stub-объектов в тестах (`SimpleNamespace(cache_gateway=FakeGateway())`) без
наследования от конкретных классов.

**Что происходит если DictionaryProviderPort не зарегистрирован?**

`deps.dictionaries = None`. При первом вызове любого `dictionary.*` провайдера — `AttributeError`.
EnricherCore перехватывает исключение как `op_error` → `_report_by_policy(on_provider_error)`.
Если `on_error: warn` — предупреждение; если `on_error: error` (дефолт) — запись с ошибкой.

**Зачем `_dataset_requires_vault()`?**

Vault — тяжёлая инфраструктура (SQLite, ключи шифрования, startup validation). Инициализировать
его для каждого датасета нецелесообразно. `_dataset_requires_vault()` позволяет включать vault
только тогда, когда DSL явно объявляет секреты — через `secrets.fields` или `target: secret:field`.

**Почему `exists`-провайдер возвращает `dict | None`, а не `bool`?**

`allow_if(result, existing)` получает `existing` и обращается к его полям (напр. `existing["match_key"]`).
Если бы `exists` возвращал `bool` — `allow_if` не мог бы принять решение на основе данных
найденной записи.

**Можно ли добавить новый порт без изменения `EnricherCore`?**

Да, именно так и работает архитектура:
1. Создать Protocol в `connector/domain/ports/`
2. Добавить атрибут в `SimpleNamespace deps` в `enricher_engine.py`
3. Зарегистрировать в `_build_enrich_context()` в `containers.py`
4. Создать провайдер в `providers/registry.py`
`EnricherCore` остаётся неизменным.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [enrich-dsl.md](enrich-dsl.md) | YAML-спецификация: EnrichRule, ProviderRef, merge-политики |
| [enrich-core.md](enrich-core.md) | EnricherCore алгоритм, CandidateValue, ConflictResolver, secrets flow |
| [vault-core.md](../vault/vault-core.md) | Vault domain: enrich → plan → apply pipeline |
| [vault-storage.md](../vault/vault-storage.md) | SQLite схема vault, SecretVaultWriteService |
| [docs/dev/layers/dictionary/](../dictionary/) | Dictionary layer (DictionaryProviderPort реализация) |
| `connector/domain/transform/providers/registry.py` | ProviderGateway исходный код |
| `connector/delivery/cli/containers.py` | DI wiring (AppContainer) |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — инфраструктура enrich-слоя | xORex-LC |
