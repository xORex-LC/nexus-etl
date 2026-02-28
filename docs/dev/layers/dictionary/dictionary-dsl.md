# Dictionary DSL

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🎯 DSL](#-dsl)
  - [Структура DSL](#структура-dsl)
  - [Registry DSL](#registry-dsl)
  - [Dictionary Spec DSL](#dictionary-spec-dsl)
  - [Manifest DSL](#manifest-dsl)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
  - [Порты](#порты)
  - [Pydantic-модели](#pydantic-модели)
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

**Назначение**: Декларативное описание статических словарей через YAML-конфигурацию с валидацией через Pydantic-модели и публикацией контракта доступа через доменный порт.

**Ключевая ответственность**:
- Определение Pydantic-моделей для трёх уровней конфигурации словарей: registry, spec и manifest
- Загрузка и валидация YAML-файлов конфигурации с fail-fast поведением через `DslLoadError`
- Задание whitelist допустимых операций нормализации ключей (`normalized_key.ops`)
- Публикация доменного порта `DictionaryProviderPort` для transform-слоя

**Расположение в кодовой базе**:
- `connector/domain/dictionary_dsl/specs.py` — Pydantic-модели DSL (без IO)
- `connector/domain/dictionary_dsl/loader.py` — загрузка и валидация YAML
- `connector/domain/dictionary_dsl/__init__.py` — публичный API модуля
- `connector/domain/ports/transform/dictionaries.py` — порт `DictionaryProviderPort`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/domain/dictionary_dsl/
├── __init__.py          # Публичный API: реэкспорт моделей и функций loader
├── specs.py             # Pydantic-модели DSL (registry/spec/manifest)
└── loader.py            # Функции загрузки YAML в Pydantic-модели

connector/domain/ports/transform/
└── dictionaries.py      # DictionaryProviderPort (Protocol)
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Dictionary DSL Class Diagram](../../uml/dictionary/dictionary_dsl_class.png) | Структура Pydantic-моделей и связи |
| Activity | [Loader Flow](../../uml/dictionary/dictionary_dsl_activity_loader.png) | Алгоритм загрузки и валидации YAML |

**PlantUML исходники**: `docs/uml/dictionary/*.puml`

> **Примечание**: Диаграммы отражают структуру Pydantic-моделей и flow функций loader.

### 🎭 Применённые паттерны

#### Паттерн 1: Declarative Validation (Pydantic v2)

**Где применяется**: Все DSL-модели (`DictionarySpec`, `DictionaryRegistrySpec`, `DictionaryManifestSpec`) используют Pydantic v2 для декларативной валидации.

**Реализация в коде**:
- **Модели**: `DictionarySpec` и другие в `connector/domain/dictionary_dsl/specs.py`
- **Валидаторы полей**: `@field_validator` для строковых полей (not-blank)
- **Валидаторы модели**: `@model_validator` для межполевых инвариантов

**Пример использования**:
```python
# Pydantic v2 model с field и model validator
class DictionarySchemaSpec(DslBaseModel):
    key_column: str
    value_columns: list[str]
    normalized_key: DictionaryNormalizedKeySpec | None = None

    @model_validator(mode="after")
    def _validate_schema(self) -> "DictionarySchemaSpec":
        _require_non_blank(self.key_column, field_name="schema.key_column")
        if not self.value_columns:
            raise ValueError("schema.value_columns must not be empty")
        if self.key_column in self.value_columns:
            raise ValueError("schema.key_column must not be present in schema.value_columns")
        return self
```

**Зачем**: Fail-fast при загрузке конфигурации, сильная типизация без ручной проверки, автодокументирование инвариантов в коде.

#### Паттерн 2: Domain Port (Protocol)

**Где применяется**: `DictionaryProviderPort` — структурный Protocol для изоляции domain от инфраструктурной реализации.

**Реализация в коде**:
- **Port**: `DictionaryProviderPort` в `connector/domain/ports/transform/dictionaries.py`
- **Adapter**: `PolarsDictionaryProvider` в `connector/infra/dictionaries/provider.py`

**Пример использования**:
```python
# Domain использует только порт — не знает о Polars или CSV
class EnrichEngine:
    def __init__(self, dictionary_provider: DictionaryProviderPort) -> None:
        self._dict = dictionary_provider

    def resolve_org(self, code: str) -> dict | None:
        rows = self._dict.lookup("organizations", code, fields=("name", "ouid"))
        return rows[0] if rows else None
```

**Зачем**: Dependency Inversion Principle — domain не зависит от инфраструктуры. Позволяет менять backend (CSV → DuckDB) без изменения domain-логики.

#### Паттерн 3: Whitelist Validation (Domain Rule)

**Где применяется**: Список допустимых операций нормализации ключей (`normalized_key.ops`) определён как domain-константа.

**Реализация в коде**:
- **Whitelist**: `DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST` в `connector/domain/dictionary_dsl/specs.py:20`
- **Применение**: `DictionaryNormalizedKeySpec._validate_ops_whitelist()` на line 116

**Пример использования**:
```python
DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST: frozenset[str] = frozenset({
    "trim", "lower", "upper", "to_string", "regex_replace"
})

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

**Зачем**: Безопасность и предсказуемость — в нормализации ключей словаря допустимы только deterministicные, side-effect-free операции.

### Диаграмма зависимостей

```
[datasets/registry.yml]  [datasets/dictionaries/*.dictionary.yaml]  [datasets/dictionaries/manifest.yml]
         ↓                               ↓                                        ↓
  [loader.py]  ←─────────────────────────────────────────────────────────────────┘
  load_*_spec()
         ↓
  [specs.py / Pydantic validation]
         ↓
  DictionaryRegistrySpec / DictionarySpec / DictionaryManifestSpec
         ↓
  [dictionary-core layer: build_dictionary_dsl_runtime()]

[DictionaryProviderPort (Protocol)]
         ↑ implements
  [PolarsDictionaryProvider — в infra layer]
         ↑ uses
  [EnrichEngine / transform operations — в domain/application layer]
```

---

## 🎯 DSL

### Структура DSL

Dictionary layer использует три уровня YAML-конфигурации:

| Уровень | Файл | Модель | Назначение |
|---------|------|--------|------------|
| Registry | `datasets/registry.yml` → секция `dictionaries` | `DictionaryRegistrySpec` | Control plane: какие словари существуют и где их specs |
| Spec | `datasets/dictionaries/*.dictionary.yaml` | `DictionarySpec` | Lookup-схема, источник данных, политика дубликатов |
| Manifest | `datasets/dictionaries/manifest.yml` | `DictionaryManifestSpec` | Fingerprint-метаданные CSV snapshot (SHA-256, row_count) |

### Registry DSL

**Расположение**: Секция `dictionaries` в `datasets/registry.yml`

```yaml
# datasets/registry.yml
dictionaries:
  version: 1
  items:
    organizations:                          # Ключ registry (должен совпадать с spec.dictionary)
      spec: dictionaries/organizations.dictionary.yaml   # Относительный путь от datasets/
      enabled: true                         # Отключить без удаления: enabled: false
    departments:
      spec: dictionaries/departments.dictionary.yaml
      enabled: false                        # Словарь объявлен, но не загружается
```

**Инварианты registry**:
- `version` фиксирован в `1` — нарушение вызывает `ValidationError`
- `items` может быть пустым `{}` — это валидный empty runtime
- Ключ в `items` (например, `organizations`) **обязан совпадать** с `spec.dictionary` внутри файла spec

**Disabled mode**: Если секция `dictionaries` **отсутствует** целиком в `registry.yml` — dictionary runtime переходит в disabled mode (`None`), не возбуждая ошибок.

### Dictionary Spec DSL

**Расположение**: Отдельный файл `datasets/dictionaries/<name>.dictionary.yaml`

```yaml
# datasets/dictionaries/organizations.dictionary.yaml
dictionary: organizations          # Имя словаря (должно совпадать с ключом registry)

source:
  format: csv                      # В v1 поддерживается только csv
  location: dictionaries/organizations.csv   # Относительный путь от datasets/
  csv:
    delimiter: ","                 # Разделитель (по умолчанию: ",")
    has_header: true               # Есть ли строка заголовков (по умолчанию: true)
    encoding: utf-8                # Кодировка файла (по умолчанию: utf-8)

schema:                            # Псевдоним: data_schema (alias в Pydantic)
  key_column: code                 # Колонка для lookup (ключ поиска)
  value_columns:                   # Колонки, возвращаемые при lookup
    - name
    - ouid
  normalized_key:                  # Опционально: цепочка нормализации ключа
    ops:
      - op: trim                   # Удалить пробелы с краёв
      - op: lower                  # Привести к нижнему регистру

lookup:
  allow_duplicates: false          # Запретить дублирующие ключи в CSV (по умолчанию: false)
```

**Доступные операции `normalized_key.ops`** (whitelist):

| Op | Описание | Параметры |
|----|----------|-----------|
| `trim` | Убрать пробелы с краёв строки | — |
| `lower` | Привести к нижнему регистру | — |
| `upper` | Привести к верхнему регистру | — |
| `to_string` | Привести к строке | — |
| `regex_replace` | Regex-замена (из `OperationRegistry`) | `old`, `new` |

**Запрещённые в `normalized_key.ops`**: любые операции за пределами whitelist. Ошибка возникает при Pydantic-валидации на этапе загрузки.

**Инварианты `schema`**:
- `key_column` — не пустая строка
- `value_columns` — не пустой список
- `key_column` **не должен** присутствовать в `value_columns` (взаимоисключающие множества)

**Пример невалидной конфигурации**:
```yaml
# ❌ Ошибка: key_column 'code' присутствует в value_columns
schema:
  key_column: code
  value_columns:
    - code      # Нарушение инварианта
    - name

# ❌ Ошибка: запрещённая операция нормализации
normalized_key:
  ops:
    - op: eval  # Не входит в whitelist
```

### Manifest DSL

**Расположение**: `datasets/dictionaries/manifest.yml`

**Назначение**: Хранит fingerprint-метаданные CSV-файлов, зафиксированные в момент последнего обновления данных. Используется для integrity-проверки при загрузке.

```yaml
# datasets/dictionaries/manifest.yml
version: 1
items:
  organizations:                                    # Ключ должен совпадать с registry-ключом
    csv_path: dictionaries/organizations.csv        # Путь к CSV (должен совпадать с spec.source.location)
    content_sha256: 59aff796321b42f93fdd63c8e32016968e3e8a9a4fc00c79caa5370286f9568a  # SHA-256 raw bytes
    schema_hash: c797aaf53db754500bb427b7b825a864911ae361a34288f4e896a9d4ac3d5854   # Hash схемы из spec
    row_count: 2                                    # Количество строк в CSV
    updated_at_utc: "2026-02-23T12:00:00Z"          # Timestamp последнего обновления
    owner: dataset-employees                        # Команда-владелец данных
```

**Что входит в `schema_hash`** (deterministic SHA-256 canonical JSON):
- `dictionary` — имя словаря
- `source.format` — формат источника
- `schema.key_column`, `schema.value_columns`, `schema.normalized_key.ops` — lookup-схема
- `lookup.allow_duplicates` — политика дубликатов

**Что НЕ входит в `schema_hash`**:
- `source.csv.delimiter`, `source.csv.encoding` — параметры парсинга (не влияют на lookup semantics)
- `manifest.updated_at_utc`, `manifest.owner` — observability-метаданные

**Когда нужно обновить manifest**: при любом изменении CSV-файла или lookup-схемы словаря. При расхождении fingerprints runtime упадёт с `DICT_SOURCE_FINGERPRINT_MISMATCH`.

---

## 🔑 Ключевые абстракции

### Порты

| Интерфейс | Назначение | Где используется |
|-----------|-----------|------------------|
| `DictionaryProviderPort` | Контракт доступа к словарям для domain/application слоя | Transform операции, enrich engine |

### Pydantic-модели

| Класс | Роль | Ключевые поля |
|-------|------|--------------|
| `DictionaryRegistrySpec` | Control plane — список словарей | `version: Literal[1]`, `items: dict[str, DictionaryRegistryItemSpec]` |
| `DictionaryRegistryItemSpec` | Одна запись в registry | `spec: str`, `enabled: bool` |
| `DictionarySpec` | Полная конфигурация одного словаря | `dictionary`, `source`, `data_schema`, `lookup` |
| `DictionarySourceSpec` | Конфигурация источника | `format: Literal["csv"]`, `location: str`, `csv: DictionarySourceCsvSpec` |
| `DictionarySourceCsvSpec` | CSV-параметры | `delimiter`, `has_header`, `encoding` |
| `DictionarySchemaSpec` | Lookup-схема | `key_column`, `value_columns`, `normalized_key` |
| `DictionaryNormalizedKeySpec` | Цепочка нормализации ключа | `ops: list[OperationCall]` |
| `DictionaryLookupSpec` | Политика lookup | `allow_duplicates: bool` |
| `DictionaryManifestSpec` | Реестр fingerprints CSV snapshot'ов | `version: Literal[1]`, `items: dict[str, DictionaryManifestItemSpec]` |
| `DictionaryManifestItemSpec` | Fingerprint одного словаря | `csv_path`, `content_sha256`, `schema_hash`, `row_count`, `updated_at_utc`, `owner` |

---

## 🗂️ Модели данных

### Protocol: `DictionaryProviderPort`

**Назначение**: Структурный Protocol (PEP 544), определяющий контракт доступа к словарям для domain и application слоёв.

**Структура**:
```python
class DictionaryProviderPort(Protocol):
    def lookup(
        self,
        dict_name: str,
        key: str,
        at: Any | None = None,           # Temporal parameter (зарезервирован для v2)
        fields: tuple[str, ...] | None = None,  # Field projection (None = все колонки)
        limit: int | None = None,        # Ограничение числа результатов
    ) -> list[dict[str, Any]]: ...

    def contains(
        self,
        dict_name: str,
        value: str,
        at: Any | None = None,
    ) -> bool: ...

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        at: Any | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
```

**Lifecycle**:
1. **Объявление**: Порт определён в `connector/domain/ports/transform/dictionaries.py`
2. **Реализация**: `PolarsDictionaryProvider` в `connector/infra/dictionaries/provider.py`
3. **Инъекция**: Через DI container (`DictionaryContainer.provider`) в transform/enrich слои

**Инварианты**:
- Реализация обязана поддерживать все три метода
- `at` параметр в v1 игнорируется (зарезервирован для temporal lookups в v2)
- Пустой runtime возвращает `[]` / `False` — не возбуждает ошибок

---

### Dataclass: `DictionarySpec`

**Назначение**: Полная декларативная конфигурация одного словаря — результат парсинга `*.dictionary.yaml`.

**Структура**:
```python
class DictionarySpec(DslBaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    dictionary: str                                           # Имя словаря
    source: DictionarySourceSpec                              # Источник данных
    data_schema: DictionarySchemaSpec = Field(alias="schema") # Lookup-схема (alias "schema" в YAML)
    lookup: DictionaryLookupSpec = Field(default_factory=DictionaryLookupSpec)
```

**Создание и использование**:
```python
# Через loader (типичный сценарий):
spec = load_dictionary_spec("datasets/dictionaries/organizations.dictionary.yaml")

# Прямая валидация (в тестах):
spec = DictionarySpec.model_validate({
    "dictionary": "organizations",
    "source": {
        "format": "csv",
        "location": "dictionaries/organizations.csv",
    },
    "schema": {
        "key_column": "code",
        "value_columns": ["name", "ouid"],
    }
})

# Доступ к полям:
print(spec.data_schema.key_column)   # "code"
print(spec.data_schema.value_columns) # ["name", "ouid"]
```

**Lifecycle**:
1. **Создание**: `load_dictionary_spec()` читает YAML → `DictionarySpec.model_validate()`
2. **Валидация**: При создании Pydantic применяет все field/model validators
3. **Передача**: Передаётся в `build_dictionary_dsl_runtime()` для компиляции в `CompiledDictionarySpec`

**Инварианты**:
- `data_schema.key_column` не входит в `data_schema.value_columns`
- `data_schema.value_columns` не пустой
- `source.format` только `"csv"` в v1
- Все строковые поля не пустые/не пробельные

---

### Dataclass: `DictionaryManifestItemSpec`

**Назначение**: Fingerprint CSV-snapshot одного словаря для integrity verification при загрузке.

**Структура**:
```python
class DictionaryManifestItemSpec(DslBaseModel):
    csv_path: str           # Путь к CSV (должен совпадать с spec.source.location)
    content_sha256: str     # SHA-256 от raw bytes CSV-файла
    schema_hash: str        # Детерминированный hash lookup-схемы
    row_count: int          # Количество строк в CSV (>= 0)
    updated_at_utc: str     # ISO timestamp последнего обновления
    owner: str              # Команда-владелец данных
```

**Lifecycle**:
1. **Создание**: Вручную или скриптом при обновлении CSV-данных
2. **Валидация**: При `build_dictionary_dsl_runtime()` — сравнение `schema_hash` с вычисленным; при `load_dictionary_into()` — сравнение `content_sha256` и `row_count` с фактическими
3. **Завершение**: Хранится неизменным в `CompiledDictionarySpec.manifest_item` на всё время жизни runtime

**Инварианты**:
- `row_count >= 0` (Pydantic `Field(ge=0)`)
- Все строковые поля непустые
- `csv_path` должен совпадать с `spec.source.location` (проверяется в `build_dictionary_dsl_runtime`)

---

## 📊 Ключевые методы и алгоритмы

### Обзор функций загрузки

| Функция | Назначение |
|---------|-----------|
| `load_dictionary_registry_spec(path?)` | Загрузить registry из файла или из `datasets/registry.yml` |
| `load_optional_dictionary_registry_spec_for_runtime()` | Graceful load — `None` если секция отсутствует |
| `load_dictionary_registry_spec_for_runtime()` | Strict load из canonical path |
| `load_dictionary_spec(path)` | Загрузить один `*.dictionary.yaml` |
| `load_dictionary_spec_for_runtime(dict_name)` | Загрузить по имени из registry |
| `load_enabled_dictionary_specs_for_runtime()` | Загрузить все enabled specs из registry |
| `load_dictionary_manifest_spec(path?)` | Загрузить `manifest.yml` |
| `load_dictionary_manifest_spec_for_runtime()` | Загрузить из canonical path |

---

### Функция: `load_enabled_dictionary_specs_for_runtime()`

**Расположение**: `connector/domain/dictionary_dsl/loader.py:124`

**Сигнатура**:
```python
def load_enabled_dictionary_specs_for_runtime() -> dict[str, DictionarySpec]:
    """
    Загрузить все enabled dictionary spec'и из registry в единый словарь.
    """
```

**Назначение**: Загрузить все активные словари из registry за одну операцию — типичная точка входа для startup initialization.

**Алгоритм**:
```
1. Загрузка registry (lines 133)
   - load_dictionary_registry_spec_for_runtime()
   - Canonical path: datasets/registry.yml → секция 'dictionaries'

2. Итерация по items (lines 137-150)
   FOR EACH (dict_name, entry) IN registry.items:
     IF entry.enabled == False:
       SKIP (continue)

     spec_path = datasets_root / entry.spec
     spec = load_dictionary_spec(spec_path)

     _validate_registry_key_matches_spec(dict_name, spec, spec_path)
     → IF spec.dictionary != dict_name: RAISE DslLoadError(DICT_DSL_SPEC_INVALID)

3. Проверка дублирующихся имён (lines 143-148)
   IF spec.dictionary IN seen_declared_names:
     RAISE DslLoadError(DICT_DSL_SPEC_INVALID, "Duplicate dictionary name")
   seen_declared_names.add(spec.dictionary)
   specs[dict_name] = spec

4. Возврат результата
   RETURN dict[str, DictionarySpec]  (ключ = registry key)
```

**Инварианты**:
1. Ключ результата совпадает с ключом в registry (`dict_name`)
2. `spec.dictionary` совпадает с ключом registry (fail-fast при расхождении)
3. Нет двух specs с одинаковым `spec.dictionary`
4. Словари с `enabled=false` не включаются в результат

**Edge cases**:
- **Пустой registry** (`items: {}`): возвращает `{}` без ошибок
- **Все словари disabled**: возвращает `{}` без ошибок
- **Дублирующийся `spec.dictionary`** в разных файлах: `DICT_DSL_SPEC_INVALID`

---

### Функция: `load_optional_dictionary_registry_spec_for_runtime()`

**Расположение**: `connector/domain/dictionary_dsl/loader.py:48`

**Назначение**: Graceful-загрузка registry с поддержкой disabled mode.

**Алгоритм**:
```
1. Читаем registry.yml (lines 58-65)
   IF ошибка IO → RAISE DslLoadError(DICT_DSL_REGISTRY_INVALID)  ← always fatal

2. Извлекаем payload (line 67)
   payload = _extract_dictionary_registry_payload(raw, allow_missing=True)

3. Проверяем disabled mode (lines 68-70)
   IF payload IS None:
     RETURN None  ← disabled mode, секция 'dictionaries' отсутствует

   RETURN _validate_registry_or_raise(path, payload)
```

**Важная граница**: Только **отсутствие секции** `dictionaries` в registry дает `None`. Ошибка чтения файла — всегда `DslLoadError` (fatal).

---

## 🛠️ Как расширять

### Добавить новый словарь

1. **Создать CSV-файл с данными**:
   ```
   datasets/dictionaries/departments.csv
   code,name,manager_id
   DEPT-01,Engineering,EMP-100
   DEPT-02,Finance,EMP-200
   ```

2. **Создать spec-файл**:
   ```yaml
   # datasets/dictionaries/departments.dictionary.yaml
   dictionary: departments
   source:
     format: csv
     location: dictionaries/departments.csv
   schema:
     key_column: code
     value_columns: [name, manager_id]
     normalized_key:
       ops:
         - op: trim
         - op: upper
   lookup:
     allow_duplicates: false
   ```

3. **Зарегистрировать в registry**:
   ```yaml
   # datasets/registry.yml → секция dictionaries
   dictionaries:
     version: 1
     items:
       departments:
         spec: dictionaries/departments.dictionary.yaml
         enabled: true
   ```

4. **Обновить manifest** (вычислить fingerprints):
   ```python
   from connector.infra.dictionaries.versioning import (
       build_content_sha256_for_file,
       build_dictionary_schema_hash,
   )
   from connector.domain.dictionary_dsl import load_dictionary_spec

   spec = load_dictionary_spec("datasets/dictionaries/departments.dictionary.yaml")
   schema_hash = build_dictionary_schema_hash(spec)
   content_sha256 = build_content_sha256_for_file("datasets/dictionaries/departments.csv")
   print(f"schema_hash: {schema_hash}")
   print(f"content_sha256: {content_sha256}")
   ```

   Добавить в `datasets/dictionaries/manifest.yml`:
   ```yaml
   items:
     departments:
       csv_path: dictionaries/departments.csv
       content_sha256: <вычисленный_hash>
       schema_hash: <вычисленный_hash>
       row_count: 2
       updated_at_utc: "2026-02-27T12:00:00Z"
       owner: dataset-employees
   ```

### Добавить новую операцию нормализации ключа

1. **Зарегистрировать operation в `OperationRegistry`** (в infra-слое):
   ```python
   # connector/domain/dsl/registry.py или в register_core_ops()
   registry.register("strip_prefix", strip_prefix_func)
   ```

2. **Добавить в whitelist** в `connector/domain/dictionary_dsl/specs.py`:
   ```python
   DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST: frozenset[str] = frozenset({
       "trim", "lower", "upper", "to_string", "regex_replace",
       "strip_prefix",  # ← новая операция
   })
   ```

3. **Использовать в DSL**:
   ```yaml
   normalized_key:
     ops:
       - op: strip_prefix
         args:
           prefix: "DEPT-"
   ```

### Добавить новый формат источника (v2+)

1. Добавить новое значение в `DictionarySourceSpec.format: Literal["csv", "parquet"]`
2. Создать аналог `DictionarySourceCsvSpec` — например, `DictionarySourceParquetSpec`
3. Обновить `CsvDictionaryLoader` или создать новый loader
4. Обновить `DictionaryContainer` для выбора правильного loader

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Dictionary Core | Предоставляет | `DictionarySpec`, `DictionaryManifestSpec` | Core получает валидированные specs для компиляции |
| Dictionary Infra | Предоставляет | `DictionaryProviderPort` (Port) | Provider реализует порт для domain |
| Transform / Enrich | Использует порт | `DictionaryProviderPort` | Lookup при обогащении данных |
| DSL Core | Наследует | `DslBaseModel`, `DslLoadError`, `OperationCall` | Общие базовые типы |
| Config | Потребляет | `DictionaryConfig` (только в delivery) | Delivery layer читает settings |

---

## 🔌 Контракты и границы

### DSL-контракт

**Формат registry** (`datasets/registry.yml`):
```yaml
dictionaries:
  version: 1
  items:
    <dict_name>:
      spec: <relative_path_to_spec>
      enabled: true | false
```

**Формат spec** (`datasets/dictionaries/*.dictionary.yaml`):
```yaml
dictionary: <name_must_match_registry_key>
source:
  format: csv
  location: <relative_path_from_datasets/>
  csv:
    delimiter: ","
    has_header: true
    encoding: utf-8
schema:                     # Обязателен; псевдоним для data_schema в Pydantic
  key_column: <column>      # Обязателен
  value_columns: [...]      # Обязателен, не пустой
  normalized_key:           # Опционален
    ops:
      - op: <whitelist_op>
lookup:
  allow_duplicates: false
```

**Схема валидации**: Pydantic v2 validators в `connector/domain/dictionary_dsl/specs.py`

**Обязательные поля spec**: `dictionary`, `source.format`, `source.location`, `schema.key_column`, `schema.value_columns`

**Опциональные поля**: `source.csv.*` (дефолты), `schema.normalized_key`, `lookup.allow_duplicates` (default: false)

---

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `specs.py` → `connector/domain/dsl/specs/_base` — базовые типы DSL
- ✅ `loader.py` → `connector/domain/dsl/issues` — `DslLoadError`
- ✅ `loader.py` → `connector/domain/dsl/loader/_common` — `_read_yaml`, `_repo_root`
- ✅ `DictionaryProviderPort` → `typing.Protocol` — только stdlib

**Запрещённые зависимости**:
- ❌ `specs.py` / `loader.py` → `connector/infra/*` — domain не зависит от инфраструктуры
- ❌ `specs.py` / `loader.py` → `polars`, `sqlite3`, `dependency_injector` — нет внешних фреймворков
- ❌ `DictionaryProviderPort` → `PolarsDictionaryBackend` — порт не знает об адаптере
- ❌ `loader.py` → CSV IO — загружает только YAML

**Визуальная граница**:
```
┌─────────────────────────────────────────────────────────────────┐
│ Domain: dictionary_dsl (specs.py + loader.py + port)            │
│   - Pydantic validation (no IO except YAML read)                │
│   - DictionaryProviderPort (Protocol, structural typing)        │
│   - DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST (domain rule)       │
└────────────▲───────────────────────────────────────────────────┘
             │ imports from
┌────────────┴───────────────────────────────────────────────────┐
│ Domain: dsl core                                                │
│   - DslBaseModel, DslLoadError, OperationCall                   │
│   - _read_yaml, _repo_root (low-level utils)                    │
└────────────────────────────────────────────────────────────────┘
             ↑ implements
┌────────────┴───────────────────────────────────────────────────┐
│ Infra: dictionaries (core + infra + delivery)                   │
│   - PolarsDictionaryProvider implements DictionaryProviderPort  │
│   - build_dictionary_dsl_runtime() consumes DictionarySpec      │
└────────────────────────────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Загрузка всех активных словарей при старте приложения

**Задача**: DI container на старте должен загрузить DSL-конфигурации всех enabled словарей.

**Решение**:
```python
# В DictionaryContainer / _load_runtime_bundle_optional()
registry = load_optional_dictionary_registry_spec_for_runtime()
if registry is None:
    return None  # disabled mode

specs = load_enabled_dictionary_specs_for_runtime()
manifest = load_dictionary_manifest_spec_for_runtime()
bundle = build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)
```

**Объяснение**: `load_optional_*` проверяет наличие секции `dictionaries` — это единственный graceful-путь. Все остальные ошибки (невалидный YAML, расхождение fingerprint) fail-fast.

---

### Сценарий 2: Валидация нового spec-файла в CI

**Задача**: Проверить корректность нового `*.dictionary.yaml` без запуска полного runtime.

**Решение**:
```python
from connector.domain.dictionary_dsl import load_dictionary_spec
from connector.domain.dsl.issues import DslLoadError

try:
    spec = load_dictionary_spec("datasets/dictionaries/new_dict.dictionary.yaml")
    print(f"OK: {spec.dictionary}, key={spec.data_schema.key_column}")
except DslLoadError as exc:
    print(f"ERROR [{exc.code}]: {exc.message}")
    print(f"Details: {exc.details}")
    exit(1)
```

**Объяснение**: Загрузка через domain loader не требует infra-слоя — только YAML + Pydantic.

---

### Сценарий 3: Lookup через DictionaryProviderPort в transform

**Задача**: Enrich engine должен обогатить поле `org_code` → полным названием организации.

**Решение**:
```python
# EnrichEngine использует только порт, не зная о backend
class OrgCodeEnricher:
    def __init__(self, dict_provider: DictionaryProviderPort) -> None:
        self._dict = dict_provider

    def enrich(self, record: dict) -> dict:
        code = record.get("org_code", "")
        rows = self._dict.lookup(
            "organizations",
            code,
            fields=("name", "ouid"),
        )
        if rows:
            record["org_name"] = rows[0]["name"]
            record["org_id"] = rows[0]["ouid"]
        return record
```

**Объяснение**: Использование `fields` параметра для projection снижает overhead при большом числе колонок.

---

### Сценарий 4: Проверка принадлежности значения к словарю

**Задача**: Проверить, что `department_code` существует в справочнике отделов.

**Решение**:
```python
def validate_department_code(code: str, dict_provider: DictionaryProviderPort) -> bool:
    return dict_provider.contains("departments", code)
```

**Объяснение**: `contains()` использует тот же in-memory key-index что и `lookup()` — O(1) lookup, но без аллокации result rows.

---

## 📌 Важные детали

### Особенности реализации

- **`schema` vs `data_schema`**: В Pydantic-модели `DictionarySpec` поле называется `data_schema` (с `alias="schema"`). В YAML пишется `schema:`. При доступе в Python-коде используется `spec.data_schema`, не `spec.schema`.

- **Strict `extra: "forbid"`**: `DictionarySpec` имеет `model_config = {"extra": "forbid"}` — лишние ключи в YAML вызывают `ValidationError`. Это защита от опечаток в именах полей.

- **Отдельный `manifest.yml` для всех словарей**: Все fingerprints живут в одном файле `datasets/dictionaries/manifest.yml`, а не в отдельных файлах рядом со spec. Это упрощает atomic-обновление и аудит.

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError(DICT_DSL_REGISTRY_INVALID)` | Невалидный YAML в registry, отсутствующая секция (strict mode) | Fail-fast при старте | Проверить `datasets/registry.yml`, убедиться что секция `dictionaries` валидна |
| `DslLoadError(DICT_DSL_SPEC_INVALID)` | Невалидный `*.dictionary.yaml`: пустой `value_columns`, `key_column` в `value_columns`, запрещённая op | Fail-fast при загрузке spec | Исправить YAML-файл словаря согласно сообщению ошибки |
| `DslLoadError(DICT_DSL_SPEC_INVALID)` — key mismatch | `spec.dictionary` не совпадает с ключом в registry | Fail-fast при `load_enabled_dictionary_specs_for_runtime()` | Синхронизировать поле `dictionary:` в spec и ключ в registry |
| `DslLoadError(DICT_DSL_SPEC_INVALID)` — duplicate | Два spec-файла с одинаковым `spec.dictionary` | Fail-fast при загрузке | Проверить на дубликаты имён в `registry.yml` |
| `DslLoadError(DICT_SOURCE_MANIFEST_MISSING)` | Файл `manifest.yml` не найден | Fail-fast при `load_dictionary_manifest_spec()` | Создать manifest, выполнить fingerprinting |
| `DslLoadError(DICT_SOURCE_MANIFEST_INVALID)` | Невалидный `manifest.yml` или ошибка парсинга | Fail-fast при валидации | Исправить `manifest.yml` |
| `ValidationError` (Pydantic) | Нарушение инвариантов модели (обычно внутри `DslLoadError`) | Оборачивается loader'ом | Исправить DSL конфигурацию |

### ⚠️ Инварианты системы

1. **Инвариант: Registry key == spec.dictionary**
   - **Что**: Ключ словаря в `registry.yml.dictionaries.items` обязан совпадать с полем `dictionary:` в spec-файле
   - **Почему важно**: Иначе lookup по имени будет находить не тот spec
   - **Где проверяется**: `_validate_registry_key_matches_spec()` в `loader.py:250`

2. **Инвариант: key_column ∉ value_columns**
   - **Что**: Колонка ключа не должна дублироваться в колонках значений
   - **Почему важно**: Логическое противоречие — ключ и значение не могут быть одним полем
   - **Где проверяется**: `DictionarySchemaSpec._validate_schema()` в `specs.py:138`

3. **Инвариант: value_columns не пуст**
   - **Что**: Словарь должен возвращать хотя бы одно значение при lookup
   - **Почему важно**: Словарь без value колонок бессмысленен
   - **Где проверяется**: `DictionarySchemaSpec._validate_schema()` в `specs.py:141`

4. **Инвариант: normalized_key.ops только из whitelist**
   - **Что**: Разрешены только `trim`, `lower`, `upper`, `to_string`, `regex_replace`
   - **Почему важно**: Безопасность и детерминизм — только safe, side-effect-free операции
   - **Где проверяется**: `DictionaryNormalizedKeySpec._validate_ops_whitelist()` в `specs.py:116`

### ⏱️ Performance заметки

**Загрузка DSL**:
- Загрузка и валидация одного spec-файла: < 1 мс (только YAML + Pydantic)
- Загрузка всего registry с 10 словарями: < 10 мс
- Нет IO-зависимостей кроме чтения YAML-файлов

**Компиляция**: Выполняется один раз при старте в `build_dictionary_dsl_runtime()` — не влияет на производительность lookup.

---

## 🔗 Связанные документы

- [Dictionary Core (Runtime)](./dictionary-core.md) — компиляция DSL в runtime, versioning
- [Dictionary Infra (Backend)](./dictionary-infra.md) — Polars backend, CSV loading
- [Dictionary Delivery](./dictionary-delivery.md) — Provider adapter, Telemetry, DI container
- [ADR: Columnar Dictionary Runtime](../../adr/transform/TRANSFORM-DEC-001-columnar-dictionary-runtime-for-enricher.md)
- [ADR: Enrich Dictionary Runtime Gap](../../adr/transform/TRANSFORM-PROBLEM-001-enrich-dictionary-runtime-gap.md)
- [DSL Core](../dsl/) — базовые типы DSL
- [Cache DSL](../cache/cache-dsl.md) — аналогичный паттерн DSL в cache-слое

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Первоначальное создание документа | xORex-LC |
