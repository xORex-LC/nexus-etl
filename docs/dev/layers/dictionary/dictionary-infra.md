# Dictionary Infra (Backend)

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

**Назначение**: Загрузка CSV snapshot'ов в память, построение in-memory key-index и выполнение lookup/contains/canonicalize операций через Polars-бэкенд.

**Ключевая ответственность**:
- Чтение CSV-файлов с верификацией `content_sha256` и `row_count` из manifest
- Парсинг CSV в `polars.DataFrame` с BOM-safe декодированием
- Построение in-memory key-index: `normalized_key → tuple[row_indexes]`
- Выполнение lookup/contains/canonicalize запросов через index O(1)
- Поддержка двух стратегий загрузки: eager (все при старте) и lazy (по первому обращению)
- Предоставление `DictionaryVersionInfo` после загрузки каждого словаря

**Расположение в кодовой базе**:
- `connector/infra/dictionaries/backends/polars_backend.py` — in-memory backend (`PolarsDictionaryBackend`)
- `connector/infra/dictionaries/loader_csv.py` — CSV loader (`CsvDictionaryLoader`, `DictionaryCsvLoadEvent`)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/infra/dictionaries/
├── loader_csv.py          # CsvDictionaryLoader: IO + manifest verification
│   ├── CsvDictionaryLoader       # Читает CSV, верифицирует fingerprints, вызывает backend
│   └── DictionaryCsvLoadEvent    # DTO события успешной загрузки (для telemetry callback)
└── backends/
    ├── __init__.py
    └── polars_backend.py  # PolarsDictionaryBackend: in-memory index + lookup
        ├── _LoadedDictionaryData  # Внутреннее состояние загруженного словаря
        └── PolarsDictionaryBackend  # Публичный класс backend
```

**Разделение ответственности**:

| Компонент | Ответственность |
|-----------|----------------|
| `CsvDictionaryLoader` | IO: чтение файлов, верификация fingerprints, парсинг CSV |
| `PolarsDictionaryBackend` | Data: хранение, индексирование, lookup операции |
| `DictionaryCsvLoadEvent` | Observability: DTO события для telemetry callback |

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Dictionary Infra Class Diagram](../../uml/dictionary/dictionary_infra_class.png) | Структура backend и loader |
| Sequence | [Load Flow](../../uml/dictionary/dictionary_infra_sequence_load.png) | Eager/lazy загрузка CSV |
| Activity | [Lookup Flow](../../uml/dictionary/dictionary_infra_activity_lookup.png) | Алгоритм lookup с нормализацией |

**PlantUML исходники**: `docs/uml/dictionary/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Strategy (Eager vs Lazy Loading)

**Где применяется**: `PolarsDictionaryBackend` поддерживает два режима инициализации данных — eager и lazy, настраиваемых через DI container.

**Реализация в коде**:
- **Eager**: `CsvDictionaryLoader.load_into(backend)` — загружает все словари при `container.init_resources()`
- **Lazy**: `backend.set_lazy_loader(callback)` — загружает словарь по первому обращению через `_load_dictionary_lazy_if_needed()`

**Пример использования**:
```python
# Eager: все данные готовы сразу
csv_loader.load_into(backend)

# Lazy: callback вызывается при первом lookup
backend.set_lazy_loader(
    lambda dict_name: csv_loader.load_dictionary_into(backend, dict_name=dict_name)
)
# Данные загружаются только когда backend.lookup("orgs", ...) впервые вызван
```

**Зачем**: Eager — предсказуемость startup, fail-fast на ошибках данных. Lazy — быстрый старт приложения, данные грузятся только если используются.

---

#### Паттерн 2: In-Memory Index (Hash Map для O(1) Lookup)

**Где применяется**: `_LoadedDictionaryData.key_index` — словарь `normalized_key → tuple[row_indexes]` для быстрого поиска.

**Реализация в коде**:
- **Построение**: `PolarsDictionaryBackend._build_key_index()` в `polars_backend.py:270`
- **Использование**: `_lookup_indexes()` в `polars_backend.py:288` — O(1) dict lookup
- **Key normalization**: `_index_key()` в `polars_backend.py:295` — hashable string representation

**Пример**:
```python
# После загрузки CSV:
# code,name,ouid
# ORG-1,Org One,100
# ORG-2,Org Two,200

key_index = {
    "v:org-1": (0,),   # normalized_key → row indexes
    "v:org-2": (1,),
}

# Lookup: O(1)
indexes = key_index.get("v:org-1")  # → (0,)
row = rows[0]  # → {"code": "ORG-1", "name": "Org One", "ouid": "100"}
```

**Зачем**: Lookup по 10K+ строк словаря требует O(1) — линейный scan по DataFrame был бы неприемлем на hot path.

---

#### Паттерн 3: Callback / Observer (Load Event)

**Где применяется**: `CsvDictionaryLoader` вызывает `on_dictionary_loaded` callback после успешной загрузки — для уведомления telemetry слоя.

**Реализация в коде**:
- **Callback type**: `DictionaryCsvLoadCallback = Callable[[DictionaryCsvLoadEvent], None]`
- **Регистрация**: `CsvDictionaryLoader.__init__(on_dictionary_loaded=...)`
- **Вызов**: `_emit_load_event()` в `loader_csv.py:183`

**Пример**:
```python
def on_loaded(event: DictionaryCsvLoadEvent) -> None:
    print(f"Loaded: {event.dict_name}, rows={event.row_count}")

loader = CsvDictionaryLoader(on_dictionary_loaded=on_loaded)
loader.load_into(backend)
# → "Loaded: organizations, rows=2"
```

**Зачем**: Loose coupling — loader не знает о telemetry. Telemetry не знает о CSV loading. Связь через event DTO.

---

#### Паттерн 4: Guard Clause (Startup-Only Policy)

**Где применяется**: `CsvDictionaryLoader.load_dictionary_into()` проверяет `backend.is_loaded()` в начале — не перезагружает уже загруженные словари.

**Реализация в коде**:
- `loader_csv.py:93`: `if backend.is_loaded(dict_name): return`
- `polars_backend.py:242`: `if dict_name in self._loaded: return` (lazy guard)

**Зачем**: Идемпотентность — повторный вызов не ломает runtime state и не вызывает двойную загрузку при lazy mode.

### Диаграмма зависимостей

```
[DictionaryDslRuntimeBundle]  ←  уже скомпилирован Core-слоем
            ↓
[PolarsDictionaryBackend]
    ├── bundle: DictionaryDslRuntimeBundle  (compiled specs)
    ├── _loaded: dict[str, _LoadedDictionaryData]  (runtime state)
    └── _lazy_loader: Callable | None  (optional lazy load callback)

[CsvDictionaryLoader]
    ├── _datasets_root: Path  (где искать CSV файлы)
    └── _on_dictionary_loaded: Callback | None

CsvDictionaryLoader.load_dictionary_into(backend, dict_name)
    ├── 1. read_bytes(datasets_root / spec.source_location)
    ├── 2. verify content_sha256  ← build_content_sha256_bytes()
    ├── 3. polars.read_csv(decoded_text)
    ├── 4. verify row_count
    ├── 5. backend.load_dictionary_frame(dict_name, frame, content_sha256)
    │       ├── _validate_columns()
    │       ├── _build_key_index()  ← normalize + index all rows
    │       ├── check allow_duplicates
    │       └── build_dictionary_version_info()
    └── 6. _emit_load_event(callback)

PolarsDictionaryBackend.lookup(dict_name, key, ...)
    ├── is_empty_runtime() → [] (disabled mode)
    ├── _require_loaded(dict_name)
    │       └── IF not loaded: _load_dictionary_lazy_if_needed()
    ├── _resolve_projection(fields)
    ├── _lookup_indexes(key)
    │       └── _normalize_lookup_key() → _index_key() → key_index.get()
    └── [_project_row(row, projection) for idx in indexes]
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `PolarsDictionaryBackend` | In-memory lookup backend | `load_dictionary_frame()`, `lookup()`, `contains()`, `canonicalize()`, `set_lazy_loader()`, `is_loaded()`, `is_empty_runtime()` |
| `CsvDictionaryLoader` | CSV IO + manifest verification orchestrator | `load_into()`, `load_dictionary_into()` |
| `_LoadedDictionaryData` | Runtime state загруженного словаря (internal) | поля: `compiled`, `frame`, `rows`, `key_index`, `version_info` |
| `DictionaryCsvLoadEvent` | DTO события загрузки (для telemetry) | поля: `dict_name`, `path`, `row_count`, `content_sha256`, `source_empty`, `version_info` |

---

## 🗂️ Модели данных

### Dataclass: `_LoadedDictionaryData`

**Назначение**: Полное runtime-состояние одного загруженного словаря — DataFrame, индекс строк и version info.

**Структура**:
```python
@dataclass(frozen=True)
class _LoadedDictionaryData:
    compiled: CompiledDictionarySpec               # Compiled DSL spec (ключ, колонки, ops)
    frame: pl.DataFrame                            # Исходный Polars DataFrame
    rows: tuple[dict[str, Any], ...]               # Строки как tuple dicts (для O(1) row access)
    key_index: dict[str, tuple[int, ...]]          # normalized_key → row_indexes
    version_info: DictionaryVersionInfo            # Version metadata
```

**Создание**:
```python
# Внутри backend.load_dictionary_frame():
rows = tuple(frame.iter_rows(named=True))
key_index = self._build_key_index(compiled=compiled, rows=rows)
version_info = build_dictionary_version_info(...)
data = _LoadedDictionaryData(compiled, frame, rows, key_index, version_info)
self._loaded[dict_name] = data
```

**Lifecycle**:
1. **Создание**: В `PolarsDictionaryBackend.load_dictionary_frame()` — после валидации колонок и дубликатов
2. **Хранение**: В `self._loaded[dict_name]` на весь lifecycle backend
3. **Доступ**: Через `_require_loaded()` — единственная точка доступа к данным

**Инварианты**:
- `rows` материализован полностью (не lazy generator)
- `key_index` строится один раз при загрузке, не пересчитывается при lookup
- `key_index[k]` содержит tuple индексов из `rows` (не данные)
- `frozen=True` — после загрузки данные неизменяемы

---

### Dataclass: `DictionaryCsvLoadEvent`

**Назначение**: DTO события успешной загрузки CSV-файла — передаётся в telemetry callback без exposing IO деталей.

**Структура**:
```python
@dataclass(frozen=True)
class DictionaryCsvLoadEvent:
    dict_name: str                   # Имя словаря
    path: str                        # Абсолютный путь к CSV-файлу (для логов)
    row_count: int                   # Фактическое количество строк
    content_sha256: str              # Вычисленный SHA-256 raw bytes
    source_empty: bool               # True если row_count == 0
    version_info: DictionaryVersionInfo  # Version metadata
```

**Lifecycle**:
1. **Создание**: В `CsvDictionaryLoader._emit_load_event()` после успешной загрузки
2. **Передача**: В callback `on_dictionary_loaded(event)` — обычно `DictionaryTelemetry.record_dictionary_loaded()`
3. **Завершение**: Не хранится в loader — используется только при вызове callback

**Инварианты**:
- `source_empty = (row_count == 0)` — вычисляется автоматически
- Создаётся только при успешной загрузке (не при ошибке)
- Не содержит plaintext lookup-ключей

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `CsvDictionaryLoader.load_dictionary_into()` | 62 | O(n) | CSV IO + verify + parse + load in backend |
| `PolarsDictionaryBackend.load_dictionary_frame()` | 54 | O(n) | Validate + build index + store |
| `PolarsDictionaryBackend._build_key_index()` | 17 | O(n) | Построить key-index из rows |
| `PolarsDictionaryBackend.lookup()` | 24 | O(k) | Lookup через index с projection |
| `PolarsDictionaryBackend._require_loaded()` | 9 | O(1) | Получить loaded data или lazy-load |

*n = количество строк в CSV, k = количество результатов lookup*

---

### Метод: `CsvDictionaryLoader.load_dictionary_into()`

**Расположение**: `connector/infra/dictionaries/loader_csv.py:84`

**Сигнатура**:
```python
def load_dictionary_into(
    self,
    backend: PolarsDictionaryBackend,
    *,
    dict_name: str,
) -> None:
    """
    Загрузить один словарь по имени в backend.
    Повторная загрузка уже загруженного словаря не выполняется.
    """
```

**Назначение**: Оркестрирует полный цикл загрузки одного словаря: чтение файла → верификация fingerprints → парсинг CSV → загрузка в backend → emit event.

**Алгоритм**:
```
1. Guard: already loaded? (line 93)
   IF backend.is_loaded(dict_name):
     RETURN  (startup-only idempotency)

2. Получить compiled spec (line 96)
   compiled = backend.bundle.get(dict_name)
   file_path = datasets_root / compiled.source_location

3. Read raw bytes (lines 98)
   raw_bytes = _read_file_bytes_or_raise(file_path, dict_name)
   IF IO error → RAISE DslLoadError(DICT_SOURCE_READ_FAILED)

4. Verify content fingerprint (lines 100-111)
   content_sha256 = build_content_sha256_bytes(raw_bytes)
   IF content_sha256 != compiled.manifest_item.content_sha256:
     RAISE DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH,
                        details: expected/actual sha256, path)

5. Parse CSV (lines 113-120)
   frame = _parse_csv_or_raise(raw_bytes, delimiter, has_header, encoding)
   → _decode_text(raw_bytes, encoding)  # BOM-safe decode
   → polars.read_csv(StringIO(text), separator, has_header)
   IF parse error → RAISE DslLoadError(DICT_SOURCE_READ_FAILED)

6. Verify row_count (lines 122-132)
   IF frame.height != compiled.manifest_item.row_count:
     RAISE DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH,
                        details: expected/actual row_count, path)

7. Load into backend (lines 134-138)
   version_info = backend.load_dictionary_frame(
       dict_name=dict_name,
       frame=frame,
       content_sha256=content_sha256,
   )
   → Внутри: validate columns, build key_index, check duplicates

8. Emit load event (lines 139-145)
   _emit_load_event(dict_name, path, row_count, content_sha256, version_info)
   → callback(DictionaryCsvLoadEvent(...))
```

**Инварианты**:
1. Загрузка выполняется не более одного раза (idempotent guard)
2. Верифицируются и `content_sha256`, и `row_count` — оба fingerprint
3. Ошибки оборачиваются в `DslLoadError` с dict_name и path в details
4. Callback вызывается только при успешной загрузке

**Edge cases**:
- **BOM в UTF-8 файле**: `_decode_text()` использует `"utf-8-sig"` для strip BOM
- **Пустой CSV** (0 строк): допустим если `manifest.row_count == 0`; устанавливает `source_empty=True` в event
- **Неизвестный dict_name**: `backend.bundle.get()` возвращает `KeyError` — ошибка wiring

---

### Метод: `PolarsDictionaryBackend.load_dictionary_frame()`

**Расположение**: `connector/infra/dictionaries/backends/polars_backend.py:64`

**Сигнатура**:
```python
def load_dictionary_frame(
    self,
    *,
    dict_name: str,
    frame: pl.DataFrame,
    content_sha256: str,
) -> DictionaryVersionInfo:
    """
    Загрузить/заменить данные словаря из готового polars.DataFrame.
    """
```

**Назначение**: Принимает уже валидированный (по fingerprint) DataFrame, строит key-index и сохраняет в runtime state.

**Алгоритм**:
```
1. Получить compiled spec (line 80)
   compiled = self.bundle.get(dict_name)

2. Validate columns (lines 81)
   _validate_columns(compiled, frame)
   required = set(compiled.allowed_columns)  # key + value columns
   missing = sorted(required - set(frame.columns))
   IF missing:
     RAISE DslLoadError(DICT_SCHEMA_INVALID, details: missing, actual)

3. Материализовать строки (line 83)
   rows = tuple(frame.iter_rows(named=True))
   (полная материализация — не lazy итератор)

4. Построить key-index (line 84)
   key_index = _build_key_index(compiled, rows)
   FOR idx, row IN enumerate(rows):
     raw_key = row.get(compiled.key_column)
     normalized = _normalize_lookup_key(compiled, raw_key)  # ops chain
     key = _index_key(normalized)  # "v:{value}" или "__none__"
     buckets.setdefault(key, []).append(idx)
   RETURN {key: tuple(indexes) for key, indexes in buckets.items()}

5. Check duplicates (lines 86-100)
   IF NOT compiled.allow_duplicates:
     duplicates = [key for key, indexes in key_index if len(indexes) > 1]
     IF duplicates:
       RAISE DslLoadError(DICT_SCHEMA_INVALID,
                          details: count, sample_duplicate_keys[:5])

6. Build version_info (lines 102-108)
   version_info = build_dictionary_version_info(
       dict_name, schema_hash, content_sha256, row_count, source_format
   )

7. Store in runtime state (lines 110-116)
   self._loaded[dict_name] = _LoadedDictionaryData(
       compiled, frame, rows, key_index, version_info
   )
   RETURN version_info
```

**Временная сложность**:
- **iter_rows**: O(n) — полный scan DataFrame
- **_build_key_index**: O(n) — один pass по всем строкам
- **duplicate check**: O(n) — один pass по key_index

**Инварианты**:
- `rows` и `key_index` строятся из одного и того же `frame`
- При `allow_duplicates=false` — max 1 row per key (верифицировано)
- Пустой DataFrame с корректными колонками допустим

---

### Метод: `PolarsDictionaryBackend.lookup()`

**Расположение**: `connector/infra/dictionaries/backends/polars_backend.py:130`

**Сигнатура**:
```python
def lookup(
    self,
    dict_name: str,
    key: str,
    *,
    at: Any | None = None,
    fields: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Найти записи словаря по ключу с projection/limit."""
```

**Алгоритм**:
```
1. Empty runtime guard (lines 144-145)
   IF is_empty_runtime():
     RETURN []  (no KeyError, graceful miss)

2. Load/get loaded data (line 146)
   loaded = _require_loaded(dict_name)
   → get from self._loaded OR lazy-load if configured

3. Resolve projection (line 147)
   projection = _resolve_projection(loaded.compiled, fields)
   IF fields is None → projection = compiled.allowed_columns (all)
   IF fields specified → validate each field is in allowed_columns
   IF invalid field → RAISE DslLoadError(DICT_SCHEMA_INVALID)

4. Lookup indexes via index (line 148)
   indexes = _lookup_indexes(loaded, key)
   → normalized_key = _normalize_lookup_key(compiled, key)  # ops chain
   → index_key = _index_key(normalized_key)  # "v:{value}" or "__none__"
   → loaded.key_index.get(index_key, ())  # O(1) dict lookup, miss → ()

5. Apply limit (lines 149-153)
   IF limit is not None:
     IF limit <= 0: RAISE ValueError("limit must be > 0")
     indexes = indexes[:limit]

6. Project rows (line 154)
   RETURN [_project_row(loaded.rows[idx], projection) for idx in indexes]
   → {field: row.get(field) for field in projection}
```

**Временная сложность**:
- **Типичный**: O(k), где k = количество результатов (обычно 0 или 1)
- **С projection**: O(k × p), где p = количество полей (обычно 2–5)
- **Hash lookup**: O(1) в average case, O(n) в worst case (hash collision — маловероятно)

**Инварианты**:
1. Возвращает `[]` при miss — никогда `None`
2. Возвращает `[]` для empty runtime (не KeyError)
3. `limit` должен быть > 0 если указан
4. Порядок результатов соответствует порядку строк в CSV

---

### Метод: `PolarsDictionaryBackend._build_key_index()`

**Расположение**: `connector/infra/dictionaries/backends/polars_backend.py:270`

**Сигнатура**:
```python
def _build_key_index(
    self,
    *,
    compiled: CompiledDictionarySpec,
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[int, ...]]:
    """Построить key-index по нормализованному lookup-ключу."""
```

**Алгоритм**:
```
buckets: dict[str, list[int]] = {}

FOR idx, row IN enumerate(rows):
  raw_key = row.get(compiled.key_column)  # Сырое значение ключа из CSV
  normalized = _normalize_lookup_key(compiled, raw_key)  # ops chain
  key = _index_key(normalized)  # Приведение к hashable строке
  buckets.setdefault(key, []).append(idx)

RETURN {key: tuple(indexes) for key, indexes in buckets.items()}
```

**`_index_key(value)`**: Приводит любое значение к hashable строке:
```python
def _index_key(self, value: Any) -> str:
    if value is None:
        return "__none__"   # Специальный sentinel для None-ключей
    return f"v:{value}"     # Префикс "v:" для исключения коллизий с "__none__"
```

**Зачем префикс `"v:"`**: Если value = `"__none__"` (строка), без префикса оно совпало бы с sentinel. С префиксом: `_index_key("__none__") = "v:__none__"` ≠ `"__none__"`.

---

### Метод: `CsvDictionaryLoader._decode_text()`

**Расположение**: `connector/infra/dictionaries/loader_csv.py:207`

**Сигнатура**:
```python
@staticmethod
def _decode_text(raw_bytes: bytes, *, encoding: str) -> str:
    """Декодировать CSV bytes в text с BOM-safe поведением для UTF-8."""
```

**Алгоритм**:
```
normalized = encoding.strip().lower().replace("_", "-")

IF normalized IN {"utf-8", "utf8"}:
  RETURN raw_bytes.decode("utf-8-sig")
  # "utf-8-sig" автоматически убирает BOM (EF BB BF) если он есть

ELSE:
  RETURN raw_bytes.decode(encoding)  # Стандартное декодирование
```

**Зачем**: CSV-файлы, экспортированные из Excel/Windows-приложений, часто содержат UTF-8 BOM. `utf-8-sig` безопасно обрабатывает как файлы с BOM, так и без него.

---

## 🛠️ Как расширять

### Добавить поддержку нового формата (Parquet, v2+)

1. **Создать новый loader**:
   ```python
   # connector/infra/dictionaries/loader_parquet.py
   class ParquetDictionaryLoader:
       def load_dictionary_into(
           self,
           backend: PolarsDictionaryBackend,
           *,
           dict_name: str,
       ) -> None:
           compiled = backend.bundle.get(dict_name)
           # Читать Parquet, верифицировать fingerprint, передать в backend
           frame = pl.read_parquet(self._datasets_root / compiled.source_location)
           backend.load_dictionary_frame(dict_name=dict_name, frame=frame, content_sha256=...)
   ```

2. **Обновить `DictionaryContainer`**: Выбирать loader по `spec.source.format`

3. **Backend не нужно менять**: `PolarsDictionaryBackend.load_dictionary_frame()` принимает `pl.DataFrame` — формат источника ему безразличен.

---

### Добавить поддержку temporal lookups (v2+)

Параметр `at: Any | None = None` зарезервирован для temporal lookups. Для реализации:

1. Изменить `_LoadedDictionaryData` — добавить `temporal_snapshots: dict[timestamp, tuple[...]]`
2. Изменить `lookup()` — при `at is not None` использовать temporal index
3. Изменить `_build_key_index()` — принимать `temporal_at` для snapshot-specific index

---

### Добавить поддержку reload словаря

Текущая политика: `startup-only` (один раз при старте). Для hot-reload:

1. Убрать idempotent guard (`if backend.is_loaded(): return`)
2. Добавить `_last_loaded_at: dict[str, datetime]` для throttling
3. Добавить атомарное обновление `self._loaded[dict_name] = new_data` (thread-safe assignment)

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Dictionary Core | Потребляет | `DictionaryDslRuntimeBundle`, `CompiledDictionarySpec` | Получает compiled specs для backend |
| Dictionary Core (versioning) | Потребляет | `build_dictionary_version_info()`, `build_content_sha256_bytes()` | Создаёт version info, верифицирует fingerprint |
| Dictionary Delivery | Предоставляет | `PolarsDictionaryBackend`, `CsvDictionaryLoader` | Container создаёт и конфигурирует |
| Dictionary Delivery | Предоставляет | `DictionaryCsvLoadEvent` | Telemetry получает через callback |
| DSL Core | Потребляет | `DslLoadError` | Типизация ошибок |

---

## 🔌 Контракты и границы

### Backend-контракт: `PolarsDictionaryBackend`

**Контракт инициализации**:
```python
backend = PolarsDictionaryBackend(
    bundle=dsl_runtime_bundle,  # Required: compiled DSL
    lazy_loader=None,           # Optional: callback для lazy load
)
```

**Контракт загрузки данных**:
```python
# Единственный способ добавить данные — через load_dictionary_frame()
version_info = backend.load_dictionary_frame(
    dict_name="organizations",
    frame=polars_dataframe,          # Must have: key_column + value_columns
    content_sha256="sha256_hex",     # Для version_info
)
```

**Контракт lookup**:
```python
# lookup: возвращает список совпадений (пустой список = miss)
rows = backend.lookup("organizations", "ORG-1", fields=("name",))
# → [{"name": "Org One"}] или []

# contains: boolean check (без аллокации rows)
ok = backend.contains("organizations", "ORG-1")
# → True или False

# canonicalize: alias для lookup без projection
rows = backend.canonicalize("organizations", "ORG-1")
# → [{"code": "ORG-1", "name": "Org One", "ouid": "100"}]
```

**Состояния backend**:
```
Инициализирован (bundle задан, данные не загружены)
    ↓ load_dictionary_frame() или lazy-trigger
Загружен (данные в _loaded[dict_name])
    ↓ lookup/contains/canonicalize
Используется (read-only, no state change)
```

**Empty runtime**: `bundle.specs == {}` → `is_empty_runtime() = True` → все операции возвращают `[]`/`False` без KeyError.

---

### Loader-контракт: `CsvDictionaryLoader`

**Контракт инициализации**:
```python
loader = CsvDictionaryLoader(
    datasets_root=None,          # None → автодетект через _repo_root()
    on_dictionary_loaded=None,   # Optional callback после загрузки
)
```

**Контракт загрузки**:
```python
# Загрузить все объявленные словари:
loader.load_into(backend)

# Загрузить один словарь (eager или lazy):
loader.load_dictionary_into(backend, dict_name="organizations")
```

**Гарантии loader**:
- Верифицируются `content_sha256` И `row_count` — оба fingerprint обязательны
- Ошибки оборачиваются в `DslLoadError` с кодом и details
- Callback вызывается только при успехе, не при ошибке
- Повторная загрузка — no-op (idempotent guard)

---

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `polars_backend.py` → `polars` — основная зависимость backend
- ✅ `polars_backend.py` → `connector/infra/dictionaries/dsl_runtime` — `CompiledDictionarySpec`, `DictionaryDslRuntimeBundle`
- ✅ `polars_backend.py` → `connector/infra/dictionaries/versioning` — `build_dictionary_version_info`
- ✅ `loader_csv.py` → `polars` — парсинг CSV
- ✅ `loader_csv.py` → `connector/infra/dictionaries/backends/polars_backend` — целевой backend
- ✅ `loader_csv.py` → `connector/infra/dictionaries/versioning` — `build_content_sha256_bytes`

**Запрещённые зависимости**:
- ❌ `polars_backend.py` / `loader_csv.py` → `connector/delivery/*` — нет знания о DI
- ❌ `polars_backend.py` → `connector/infra/dictionaries/telemetry` — backend не знает о telemetry
- ❌ `loader_csv.py` → `connector/infra/dictionaries/provider` — нет обратных зависимостей
- ❌ `polars_backend.py` → filesystem напрямую — нет IO в backend, только в loader

**Визуальная граница**:
```
┌─────────────────────────────────────────────────────────────────────┐
│ Dictionary Infra: backends/polars_backend.py                         │
│   INPUT:  DictionaryDslRuntimeBundle (from Core)                     │
│   INPUT:  pl.DataFrame (from CsvDictionaryLoader via load_frame())   │
│   OUTPUT: DictionaryVersionInfo (при load_dictionary_frame())        │
│   OUTPUT: list[dict] / bool (при lookup/contains/canonicalize)       │
│   NO IO:  нет файлового доступа, только in-memory операции           │
└────────────────────────────────────────────────────────────────────┘
             ↑ frame передаётся
┌────────────┴────────────────────────────────────────────────────────┐
│ Dictionary Infra: loader_csv.py                                       │
│   INPUT:  datasets_root + compiled.source_location (file path)        │
│   INPUT:  manifest fingerprints (via CompiledDictionarySpec)          │
│   OUTPUT: вызов backend.load_dictionary_frame()                       │
│   OUTPUT: DictionaryCsvLoadEvent (via callback)                       │
│   IO:     file read, SHA-256 computation                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Eager загрузка всех словарей при старте

**Задача**: Загрузить все CSV-файлы при инициализации контейнера.

**Решение**:
```python
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader

# Backend инициализируется с compiled bundle (без данных)
backend = PolarsDictionaryBackend(bundle=runtime_bundle)

# Loader загружает все CSV в backend
loader = CsvDictionaryLoader(
    datasets_root=None,  # auto-detect
    on_dictionary_loaded=telemetry.record_dictionary_loaded,
)
loader.load_into(backend)

# Теперь backend готов к lookup
rows = backend.lookup("organizations", "ORG-1")
```

---

### Сценарий 2: Lazy загрузка по первому обращению

**Задача**: Не грузить CSV при старте, загружать только при первом обращении.

**Решение**:
```python
backend = PolarsDictionaryBackend(bundle=runtime_bundle)
loader = CsvDictionaryLoader(datasets_root=None)

# Настроить lazy loader callback
backend.set_lazy_loader(
    lambda dict_name: loader.load_dictionary_into(backend, dict_name=dict_name)
)

# Первый lookup триггерит загрузку
rows = backend.lookup("organizations", "ORG-1")
# → В момент вызова: loader.load_dictionary_into(backend, dict_name="organizations")
# → CSV читается, верифицируется, парсится, загружается в backend
# → Возвращается результат lookup
```

---

### Сценарий 3: Lookup с projection и limit

**Задача**: Получить только название организации по коду, не более 1 результата.

**Решение**:
```python
rows = backend.lookup(
    "organizations",
    " ORG-1 ",              # Нормализуется автоматически: trim → lower → "org-1"
    fields=("name",),       # Projection: только поле "name"
    limit=1,                # Не более 1 результата
)
# → [{"name": "Org One"}]

# Полный результат без projection:
rows = backend.lookup("organizations", "ORG-1")
# → [{"code": "ORG-1", "name": "Org One", "ouid": "100"}]
```

---

### Сценарий 4: Contains check без аллокации rows

**Задача**: Проверить, существует ли код в словаре — без получения полной строки.

**Решение**:
```python
# contains работает через тот же key_index, но не аллоцирует row dicts
is_valid = backend.contains("organizations", " ORG-1 ")
# → True (нормализация применяется автоматически)

is_valid = backend.contains("organizations", "NONEXISTENT")
# → False
```

**Объяснение**: `contains()` — O(1) dict lookup + нормализация, без создания `list[dict]`. Используй вместо `len(backend.lookup(...)) > 0` когда нужна только проверка существования.

---

### Сценарий 5: Диагностика duplicate keys при загрузке

**Задача**: CSV-файл содержит дублирующийся ключ, `allow_duplicates=false` — ошибка при загрузке.

**Контекст**:
```csv
# organizations.csv (некорректный)
code,name,ouid
ORG-1,Org One,100
org-1,Org One Duplicate,101  # После trim+lower совпадает с ORG-1
```

**Что происходит**:
```
backend.load_dictionary_frame("organizations", frame, sha256)
→ _build_key_index() → key_index["v:org-1"] = (0, 1)
→ duplicates = ["v:org-1"]
→ RAISE DslLoadError(
    code="DICT_SCHEMA_INVALID",
    message="Duplicate dictionary keys are not allowed for 'organizations'",
    details={"duplicates_count": 1, "sample_duplicate_keys": ["v:org-1"]}
  )
```

**Решение**: Исправить CSV (убрать дубликаты) или установить `lookup.allow_duplicates: true` в spec (если дубликаты допустимы).

---

## 📌 Важные детали

### Особенности реализации

- **`rows: tuple[dict, ...]` vs DataFrame**: После загрузки строки материализуются в `tuple` Python dicts через `frame.iter_rows(named=True)`. Это ускоряет `_project_row()` — нет overhead Polars на single-row access в hot path.

- **`key_index` хранит индексы, не данные**: `key_index["v:org-1"] = (0, 1)` — не `(row0, row1)`. Это экономит память при дублирующихся ключах (`allow_duplicates=true`).

- **Lazy recursion guard**: `self._loading_in_progress: set[str]` защищает от рекурсивного вызова lazy loader — если при загрузке словаря A происходит lookup по словарю A.

- **`set_lazy_loader(None)`**: Позволяет отключить lazy load после eager-загрузки (хотя это не обязательно, т.к. guard `is_loaded()` не даст перегрузить).

- **DataFrame хранится в `_LoadedDictionaryData.frame`**: Для возможности будущего использования в v2 (например, Polars streaming или temporal snapshots). В v1 основной источник правды — `rows` tuple.

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError(DICT_SOURCE_READ_FAILED)` | CSV-файл не найден или ошибка чтения | Fail-fast при `load_dictionary_into()` | Проверить путь в `source.location`, наличие файла |
| `DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH)` — content | SHA-256 файла не совпадает с manifest | Fail-fast при загрузке | Обновить `content_sha256` в manifest или восстановить CSV |
| `DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH)` — row_count | Количество строк не совпадает с manifest | Fail-fast при загрузке | Обновить `row_count` в manifest или восстановить CSV |
| `DslLoadError(DICT_SCHEMA_INVALID)` — missing columns | CSV не содержит объявленных колонок | Fail-fast при `load_dictionary_frame()` | Исправить CSV или spec: проверить `key_column` и `value_columns` |
| `DslLoadError(DICT_SCHEMA_INVALID)` — duplicates | Дублирующиеся normalized ключи при `allow_duplicates=false` | Fail-fast при `load_dictionary_frame()` | Убрать дубликаты из CSV или установить `allow_duplicates: true` |
| `DslLoadError(DICT_SCHEMA_INVALID)` — unknown fields | В `fields` projection указана колонка вне `allowed_columns` | Fail-fast при `lookup()` | Исправить список `fields` в вызове lookup |
| `KeyError` | `lookup/contains` с неизвестным `dict_name` в не-empty runtime | Исключение в `_require_loaded()` | Проверить, что словарь объявлен и enabled в registry |
| `RuntimeError` — recursive lazy load | Lazy loader вызвал lookup по тому же словарю | Исключение в `_load_dictionary_lazy_if_needed()` | Устранить рекурсивную зависимость в инициализации |
| `ValueError` | `limit <= 0` при lookup | ValueError в `lookup()` | Передавать только положительный limit |

### ⚠️ Инварианты системы

1. **Инвариант: rows и key_index консистентны**
   - **Что**: `key_index[k] = (idx1, idx2)` означает `rows[idx1]` и `rows[idx2]` — строки с этим ключом
   - **Почему важно**: Несоответствие даст неверные результаты lookup
   - **Где проверяется**: Обеспечивается тем, что `rows` и `key_index` строятся из одного `frame` в `load_dictionary_frame()`

2. **Инвариант: только одна загрузка per dict**
   - **Что**: Каждый словарь загружается не более одного раза
   - **Почему важно**: Перегрузка могла бы изменить key_index во время concurrent lookup
   - **Где проверяется**: `is_loaded()` guard в `load_dictionary_into()` (line 93) и в `_load_dictionary_lazy_if_needed()` (line 242)

3. **Инвариант: content_sha256 и row_count оба верифицированы**
   - **Что**: Загружается только файл, чей SHA-256 И row_count совпадают с manifest
   - **Почему важно**: Защита от частично обновлённых файлов
   - **Где проверяется**: `load_dictionary_into()` lines 100-132

4. **Инвариант: `normalized_key` одинаково применяется при build и lookup**
   - **Что**: Ключ нормализуется одной и той же цепочкой ops и при построении index, и при каждом lookup
   - **Почему важно**: Иначе lookup не найдёт существующий ключ
   - **Где проверяется**: Оба места используют `compiled.normalize_key()` через `_normalize_lookup_key()`

### ⏱️ Performance заметки

**Узкие места**:

1. **`frame.iter_rows(named=True)`** в `load_dictionary_frame()` — O(n × cols)
   - **Проблема**: Полная материализация DataFrame в Python dicts
   - **Текущая оптимизация**: Выполняется один раз при загрузке, не при lookup
   - **Дальнейшие планы**: Lazy row materialization в v2 для очень больших словарей

2. **`_build_key_index()`** — O(n) при загрузке
   - **Текущая оптимизация**: Выполняется один раз, результат кэшируется в `key_index`
   - **Эффект**: Lookup после загрузки — O(1)

3. **`normalize_key()` на hot path**
   - **Проблема**: Вызывается при каждом lookup
   - **Текущая оптимизация**: Pre-compiled callable chain (нет runtime parsing)
   - **Benchmark**: Цепочка из 2 операций ≈ 0.3–0.5 мкс

**Оптимизации**:
- **Tuple rows vs list**: `tuple` дешевле `list` по памяти, индексация O(1)
- **`key_index` stores indexes**: Не дублирует данные строк
- **Projection**: `fields` параметр позволяет избежать копирования ненужных полей
- **`contains()` vs `lookup()`**: `contains()` не аллоцирует result dicts

**Benchmark данные**:
- Загрузка словаря с 10K строк: ≈ 50 мс (доминирует `iter_rows`)
- Lookup по 10K словарю: ≈ 1–2 мкс (hash lookup + normalize + project)
- Contains check: ≈ 0.5–1 мкс

### Частые ошибки

- ❌ **Не делай так**: Передавать `list` как `fields` параметр — `lookup("orgs", key, fields=["name"])`. Тип `fields` — `tuple[str, ...] | None`
- ✅ **Делай так**: `lookup("orgs", key, fields=("name",))`

- ❌ **Не делай так**: Проверять существование через `len(backend.lookup(...)) > 0`
- ✅ **Делай так**: `backend.contains(...)` — без аллокации rows

- ❌ **Не делай так**: Вызывать `load_into()` дважды в одном lifecycle
- ✅ **Делай так**: Guard `is_loaded()` это предотвращает, но лучше явно не дублировать вызовы

---

## 🔗 Связанные документы

- [Dictionary DSL](./dictionary-dsl.md) — Pydantic-модели, порт (вход для Infra)
- [Dictionary Core](./dictionary-core.md) — Runtime compilation, versioning
- [Dictionary Delivery](./dictionary-delivery.md) — DI container, Provider, Telemetry
- [ADR: Columnar Dictionary Runtime](../../adr/transform/TRANSFORM-DEC-001-columnar-dictionary-runtime-for-enricher.md)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Первоначальное создание документа | xORex-LC |
