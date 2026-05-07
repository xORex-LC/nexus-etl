# Mapper Core — чтение источника, применение правил и интеграция с pipeline

> **Mapper Core** — runtime-ядро mapper-слоя: читает данные из источника (`CsvRecordSource`),
> оборачивает их в `SourceRecord` (`Extractor`), применяет DSL-правила (`MapperCore`) и
> передаёт `TransformResult[Mapping[str, Any]]` следующей стадии pipeline.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO: Добавить новый тип источника](#️-how-to-добавить-новый-тип-источника)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

Mapper-слой — первая стадия transform-pipeline. Он отвечает за два шага:

1. **Extract**: прочитать данные из внешнего источника (CSV-файл) → `SourceRecord`
2. **Map**: применить DSL-правила к `SourceRecord` → `TransformResult[Mapping[str, Any]]`

**Полный путь данных:**

```
CSV файл
  → CsvRecordSource.__iter__()         # infra: читает строки CSV
      → SourceRecord(line_no, values)  # domain: иммутабельная запись
          → Extractor.run()            # domain: оборачивает в TransformResult[None]
              → MapStage.run()         # domain/stages: вызывает mapper
                  → MapperEngine.map() # domain/mapping: DSL-движок
                      → MapperCore._apply_rules()  # бизнес-логика правил
                          → TransformResult[Mapping[str, Any]]
                              → NormalizeStage → EnrichStage → ...
```

**Что передаётся следующей стадии (normalize):**

`TransformResult[Mapping[str, Any]]` с полями:

| Поле | Значение после map |
|------|--------------------|
| `record` | Исходный `SourceRecord` (сохраняется на всём пути pipeline) |
| `row` | `dict[str, Any]` с маппированными полями — или `None` при ошибке |
| `row_ref` | `None` (заполняет normalize-стадия) |
| `match_key` | `None` (заполняет enrich-стадия) |
| `meta` | `dict` из MetaRule (если не было ошибок) |
| `errors` | `tuple[DiagnosticItem, ...]` — ошибки маппинга |
| `warnings` | `tuple[DiagnosticItem, ...]` — предупреждения |

---

## 🏗️ Архитектура слоя

### Компоненты и зависимости

```
infra/sources/                    domain/ports/transform/
  CsvRecordSource                   RowSource (Protocol)
        ↓ SourceRecord              SourceMapper (base class)
        ↓                                  ↑
domain/transform/core/            domain/transform/mapping/
  Extractor                         MapperEngine
  SourceRecord                        └── MapperCore
  TransformResult                           └── CompiledMapRules (из MapperDsl)
  TransformResultBuilder                    └── TransformationEngine (ops)

domain/transform/stages/
  MapStage
    ├── Extractor → TransformResult[None]
    └── MapperEngine.map() → TransformResult[Mapping]
```

### Ответственность компонентов

| Компонент | Слой | Ответственность |
|-----------|------|-----------------|
| `RowSource` | domain/ports | Протокол любого итерируемого источника записей |
| `CsvRecordSource` | infra/sources | Чтение CSV в `SourceRecord` |
| `SourceRecord` | domain/transform/core | Иммутабельная запись из источника |
| `Extractor` | domain/transform/core | Оборачивает `RowSource` → `TransformResult[None]`, перехватывает ошибки источника |
| `SourceMapper` | domain/ports | Base class для маппера (`map(record) -> TransformResult`) |
| `MapperEngine` | domain/transform/mapping | DSL-движок: загружает spec, делегирует в `MapperCore` |
| `MapperCore` | domain/transform/mapping | Применяет `CompiledMapRules` к `SourceRecord` |
| `MapStage` | domain/transform/stages | Стадия pipeline: соединяет Extractor → MapperEngine |

---

## 🔑 Ключевые абстракции

### RowSource Protocol

**Файл:** `connector/domain/ports/transform/sources.py`

```python
class RowSource(Protocol):
    def __iter__(self) -> Iterable[SourceRecord]:
        """Итерирует SourceRecord из источника данных."""
        ...
```

Structural typing — любой класс с `__iter__() -> Iterable[SourceRecord]` удовлетворяет
протоколу без явного наследования. `CsvRecordSource` реализует его именно так.

### SourceMapper

**Файл:** `connector/domain/ports/transform/sources.py`

```python
class SourceMapper(Generic[T]):
    def map(self, record: SourceRecord) -> TransformResult[T]:
        """Трансформировать SourceRecord в TransformResult."""
        raise NotImplementedError
```

`MapperEngine` наследует `SourceMapper[Mapping[str, object]]` и реализует `map()`.
`MapStage` держит ссылку на `SourceMapper` — не на конкретный класс.

### SourceRecord

**Файл:** `connector/domain/transform/core/source_record.py`

```python
@dataclass(frozen=True)
class SourceRecord:
    line_no: int                  # Номер строки в источнике (1-based)
    record_id: str                # "line:{line_no}" — уникальный идентификатор
    values: Mapping[str, Any]     # column_name → value (именованные или col_N)
```

Создаётся в `CsvRecordSource.__iter__()` и **не изменяется** на всём пути pipeline.
Все downstream-стадии могут обратиться к оригинальным данным через `result.record.values`.

### TransformResult[T]

**Файл:** `connector/domain/transform/core/result.py`

```python
@dataclass(frozen=True, slots=True)
class TransformResult(Generic[T]):
    record: SourceRecord                      # Всегда присутствует
    row: T | None                             # Результат стадии или None при ошибке
    row_ref: RowRef | None                    # Для диагностики (None после map)
    match_key: MatchKey | None                # Для дедупликации (None после map)
    meta: Mapping[str, Any]                   # Системные метаданные
    secret_candidates: Mapping[str, str]      # Кандидаты на секреты
    errors: tuple[DiagnosticItem, ...]        # Ошибки стадий
    warnings: tuple[DiagnosticItem, ...]      # Предупреждения стадий
```

**Иммутабельность:** `frozen=True`, `slots=True`. `meta` и `secret_candidates`
в `__post_init__` оборачиваются в `MappingProxyType`.

**Мутация через `with_*` методы** (создают новый объект):
- `with_row(row)` — заменить `row`
- `with_row_ref(row_ref)` — установить `row_ref`
- `with_match_key(key)` — установить `match_key`
- `with_meta_update(update)` — merged update `meta`
- `with_added_errors(errors)` — добавить ошибки
- `as_builder()` — получить `TransformResultBuilder` (mutable)

### MapperEngine

**Файл:** `connector/domain/transform/mapping/mapper_engine.py`

```python
class MapperEngine(SourceMapper[Mapping[str, object]]):
    def __init__(
        self,
        spec: MappingSpec,
        *,
        catalog: ErrorCatalog,
        dsl: MapperDsl | None = None,
        sink_spec: SinkSpec | None = None,
        options: MapDslBuildOptions | None = None,
    ) -> None:
        self.dsl = dsl or MapperDsl(options=options)
        compiled = self.dsl.compile(spec, sink_spec=sink_spec)
        self.core = MapperCore(compiled, self.dsl.engine, sink_spec=sink_spec)

    def map(self, record: SourceRecord) -> TransformResult[Mapping[str, object]]:
        return self.core.map_record(record, catalog=self.catalog)
```

Роль: DSL-обвязка — загружает и компилирует spec при инициализации,
делегирует каждый вызов `map()` в `MapperCore`.

**Фабричный метод `from_dataset()`:**

```python
@classmethod
def from_dataset(
    cls,
    *,
    dataset: str,
    catalog: ErrorCatalog,
    engine: TransformationEngine | None = None,  # hook для тестов
    options: MapDslBuildOptions | None = None,   # hook для тестов
) -> "MapperEngine":
    spec = load_mapping_spec_for_dataset(dataset)
    sink_spec = load_sink_spec_for_dataset(dataset)
    dsl_options = options or load_map_build_options_for_dataset(dataset)
    dsl = MapperDsl(engine=engine, options=dsl_options)
    return cls(spec, catalog=catalog, dsl=dsl, sink_spec=sink_spec, options=dsl_options)
```

### MapperCore

**Файл:** `connector/domain/transform/mapping/mapper_core.py`

```python
class MapperCore:
    def __init__(
        self,
        compiled: CompiledMapRules,
        engine: TransformationEngine,
        *,
        sink_spec: SinkSpec | None = None,
    ) -> None:
        self.compiled = compiled
        self.engine = engine
        self._source_index = {name: idx for idx, name in enumerate(compiled.source_columns or [])}
        self.sink_spec = sink_spec
```

`_source_index` — `dict{имя_колонки: позиция}` для позиционного fallback:
`"raw_id" → 0 → "col_0"`.

---

## 🗂️ Модели данных

### MappingOutcome (внутренняя)

**Файл:** `connector/domain/transform/mapping/mapper_core.py`

```python
@dataclass
class MappingOutcome:
    row: dict[str, Any] | None    # Mutable словарь во время построения; None при ошибке
    meta: dict[str, Any]          # Метаданные из MetaRule
    errors: list[DiagnosticItem]
    warnings: list[DiagnosticItem]
```

Промежуточный mutable результат внутри `_apply_rules()`. После завершения конвертируется
в иммутабельный `TransformResult` в `map_record()`.

### TransformResultBuilder

**Файл:** `connector/domain/transform/core/result.py`

```python
@dataclass
class TransformResultBuilder(Generic[T]):
    """Mutable builder для TransformResult."""
    _base: TransformResult[T]
    record: SourceRecord | None = None
    row: T | None = None
    ...
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)

    def build(self) -> TransformResult[T]: ...
    def add_error_item(self, item) -> DiagnosticItem: ...
    def add_warning_item(self, item) -> DiagnosticItem: ...
    def update_meta(self, update) -> "TransformResultBuilder[T]": ...
```

Используется в `MapStage` для слияния meta и errors из extractor и mapper.

---

## 📊 Ключевые методы и алгоритмы

### CsvRecordSource — чтение CSV

**Файл:** `connector/infra/sources/csv_reader.py`

**Два режима:** зависит от `has_header: bool`.

#### Режим с заголовком (`has_header=True`)

```python
reader = csv.DictReader(f, delimiter=",")
for csv_line_no, row in enumerate(reader, start=2):  # строка 1 — заголовок
    if None in row:  # лишние колонки
        raise CsvFormatError(f"Invalid column count at line {csv_line_no}: ...")
    values = {key: parseNull(row.get(key)) for key in row}
    yield SourceRecord(line_no=csv_line_no, record_id=f"line:{csv_line_no}", values=values)
```

Ключи `values` — имена колонок из заголовка (`{"raw_id": "u-001", "full_name": "Иванов"}`).

#### Режим без заголовка (`has_header=False`)

```python
reader = csv.reader(f, delimiter=",")
expected_len: int | None = None
for csv_line_no, row in enumerate(reader, start=1):  # нумерация с 1
    if expected_len is None:
        expected_len = len(row)
    elif len(row) != expected_len:
        raise CsvFormatError(f"Invalid column count at line {csv_line_no}: ...")
    values = {f"col_{idx}": parseNull(value) for idx, value in enumerate(row)}
    yield SourceRecord(line_no=csv_line_no, record_id=f"line:{csv_line_no}", values=values)
```

Ключи `values` — позиционные: `{"col_0": "u-001", "col_1": "Иванов"}`.
Первая строка задаёт ожидаемую длину; последующие строки с другой длиной → `CsvFormatError`.

**`parseNull(value)`** (из `csv_utils.py`) — конвертирует пустую строку `""` в `None`.
Кодировка `utf-8-sig` автоматически снимает BOM в UTF-8 файлах.

### Extractor.run() — оборачивание источника

**Файл:** `connector/domain/transform/core/extractor.py`

```python
def run(self) -> Iterable[TransformResult[None]]:
    try:
        for record in self.source:
            yield TransformResult(
                record=record, row=None, row_ref=None, match_key=None,
                errors=[], warnings=[],
            )
    except Exception as exc:
        row_ref = RowRef(line_no=0, row_id="source", ...)
        error = diag_error(
            catalog=self.catalog, stage=DiagnosticStage.EXTRACT,
            code="SOURCE_ERROR", message=str(exc), record_ref=row_ref,
        )
        yield TransformResult(
            record=SourceRecord(line_no=0, record_id="source", values={}),
            row=None, row_ref=row_ref,
            errors=(error,), warnings=(),
        )
```

Ключевой момент: если источник бросает исключение (`CsvFormatError`, `IOError`, etc.) —
pipeline **не падает**. Вместо этого порождается специальная запись с `SOURCE_ERROR`
диагностикой. Downstream-стадии видят `result.errors != ()` и пробрасывают
такую запись без обработки.

### MapperCore.map_record() — центральная точка входа

```python
def map_record(self, record: SourceRecord, *, catalog: ErrorCatalog) -> TransformResult[Mapping[str, Any]]:
    outcome = self._apply_rules(record, catalog)
    return TransformResult(
        record=record,
        row=outcome.row,           # None если есть errors
        row_ref=None,              # заполняется normalize-стадией
        match_key=None,            # заполняется enrich-стадией
        meta=outcome.meta,
        secret_candidates={},      # заполняется resolve-стадией
        errors=tuple(outcome.errors),
        warnings=tuple(outcome.warnings),
    )
```

### MapperCore._apply_rules() — центральный алгоритм

```
Вход: SourceRecord
Выход: MappingOutcome

1. Инициализация: row={}, meta={}, errors=[], warnings=[]

2. for rule in compiled.rules:
   ┌─ a. _resolve_rule_value(record, row, rule) → (value, issues):
   │      Если rule.sources (список):
   │        → для каждого name: _read_source(record, name) → value
   │        → собираем [v1, v2, ...] как list
   │      Иначе rule.source (одно поле):
   │        → _read_source(record, rule.source) → (value, exists)
   │        → если not exists и source is not None → DslIssue(ERROR, "missing_source_column")
   │      Если rule.ops не пустой:
   │        → apply_ops(engine, value, rule.ops) → (resolved_value, op_issues)
   │        → issues.extend(op_issues)
   │      return (value_or_resolved, issues)
   │
   ├─ b. _append_issues(issues, errors, warnings, rule, catalog, record):
   │      Маршрутизация по rule.on_error:
   │        on_error="error" → ERROR → errors.append(DiagnosticItem)
   │        on_error="warn"  → ERROR → warnings.append(DiagnosticItem)
   │        WARN severity всегда → warnings
   │
   ├─ c. Если есть ERROR в issues → skip _assign_targets, continue
   │
   └─ d. _assign_targets(row, rule, value, ...):
          targets = rule.targets or [rule.target]
          Если rule.targets (несколько):
            value is dict  → row[t] = value.get(t) для каждого t
            value is list  → row[t] = value[idx] позиционно
            иначе          → row[t] = value для всех t
          Иначе (одно):
            row[targets[0]] = value
          Если rule.required:
            → _is_present(row[target]) → False → добавить REQUIRED_FIELD_MISSING

3. _validate_schema(row, errors, ...):
   Если compiled.schema_ задана:
     for field in schema_.required:
       if not _is_present(row.get(field)):
         → REQUIRED_FIELD_MISSING error

4. _validate_sink(row, errors, ...):
   Если sink_spec задан:
     validate_sink_row(row, sink_spec, check_types=False)
     Несовпадения → warnings (не errors), on_error="warn"

5. if not errors:  # только при успешном маппинге
   for meta_rule in compiled.meta:
     _resolve_meta_value(record, row, meta_rule) → (value, issues)
     _set_meta(meta, meta_rule.target, value)  # dotted path

6. final_row = row if not errors else None

return MappingOutcome(row=final_row, meta=meta, errors=errors, warnings=warnings)
```

### `_read_source(record, name)` — позиционный fallback

```python
def _read_source(self, record: SourceRecord, name: str | None) -> tuple[Any, bool]:
    if name is None:
        return None, False
    raw = record.values
    # 1. Именованный ключ (заголовочный CSV)
    if name in raw:
        return raw.get(name), True
    # 2. Позиционный ключ (headerless CSV через source_columns)
    index = self._source_index.get(name)
    if index is not None:
        alt = f"col_{index}"
        if alt in raw:
            return raw.get(alt), True
    return None, False
```

Позволяет маппингу с именованными source полями (`source: raw_id`)
работать с позиционными CSV (`col_0`), если задан `source_columns`.

### `_is_present(value)` — проверка заполненности

```python
def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True
```

`required: true` в `MappingRule` и `schema.required` используют эту проверку.
`None`, пустая строка `""`, строка из пробелов `"  "` — считаются отсутствующими.

### `_set_meta(meta, path, value)` — dotted path запись

```python
def _set_meta(self, meta: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = meta
    for key in parts[:-1]:
        current = current.setdefault(key, {})
    current[parts[-1]] = value
```

`target: "row.source_type"` → `meta["row"]["source_type"] = value`.
Вложенность поддерживается через `setdefault` — промежуточные словари создаются автоматически.

---

## 🔄 Взаимодействие с другими слоями

### MapStage — стадия pipeline

**Файл:** `connector/domain/transform/stages/stages.py`

```python
class MapStage:
    stage_name: str = "map"

    def __init__(self, mapper: SourceMapper, catalog: ErrorCatalog) -> None:
        self.mapper = mapper

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            # 1. Запись с ошибкой из extractor → пробросить с row=None
            if collected.errors:
                builder = collected.as_builder()
                builder.set_row(None)
                yield builder.build()
                continue

            # 2. Маппинг с diagnostic boundary (перехват неожиданных исключений)
            boundary_errors: list = []
            mapped: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MAP,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=collected.row_ref,
            ):
                mapped = self.mapper.map(collected.record)

            # 3. Если mapper бросил исключение → boundary его поймал
            if mapped is None:
                builder = collected.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue

            # 4. Успешный маппинг: слияние meta и errors
            builder = mapped.as_builder()
            if collected.meta:
                builder.meta = {**collected.meta, **builder.meta}  # MAP перезаписывает EXTRACT
            builder.errors = [*collected.errors, *boundary_errors, *builder.errors]
            builder.warnings = [*collected.warnings, *builder.warnings]
            yield builder.build()
```

Ключевые инварианты:
- **Stateless:** нет состояния между вызовами `run()`
- **Ошибки не проходят через маппинг:** записи с `errors` пробрасываются с `row=None`
- **`diagnostic_boundary`** перехватывает неожиданные исключения внутри `mapper.map()`
- **Meta мержится:** `{**collected.meta, **builder.meta}` — MAP-значения приоритетнее EXTRACT

### PipelineOrchestrator — lazy chain стадий

**Файл:** `connector/domain/transform/stages/stages.py`

```python
class PipelineOrchestrator:
    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        current: Iterable[TransformResult] = source
        for stage in self._stages:
            if self._hooks.on_stage_bind:
                self._hooks.on_stage_bind(stage.stage_name)  # eager: при сборке
            current = self._execute_stage(stage, current)
        return current  # lazy итератор — данные не потребляются
```

**Lazy pipeline:** `PipelineOrchestrator.run()` возвращает итератор, данные не потребляются
до первого `for` на конечном потребителе. Это означает:
- `MapStage.run()` реально стартует при первом `next()` с конца цепочки
- `CsvRecordSource` открывает файл при первом `next()` из `Extractor`

Мониторинг через `PipelineHooks`:
- `on_stage_start` — при первом элементе из стадии (lazy)
- `on_stage_complete` — при исчерпании (`StopIteration`)
- `on_stage_error` — при исключении после первого элемента
- `on_stage_abort` — при `GeneratorExit` (partial consumption)

### Сборка в delivery

```python
# connector/delivery/cli/containers.py или pipeline_registry.py

source_spec = load_source_spec_for_dataset(dataset)
source_path = resolve_source_location(source_spec)
has_header = source_spec.source.options.get("has_header_default", True)

# Infra: конкретный источник
source = CsvRecordSource(path=source_path, has_header=has_header)

# Domain: extractor оборачивает источник
extractor = Extractor(source=source, catalog=catalog)

# Domain: mapper создаётся из датасета
mapper = MapperEngine.from_dataset(dataset=dataset, catalog=catalog)

# Стадии pipeline
map_stage = MapStage(mapper=mapper, catalog=catalog)
normalize_stage = NormalizeStage(normalizer=normalizer_engine, catalog=catalog)
# ...

# Orchestrator: lazy chain
pipeline = PipelineOrchestrator([map_stage, normalize_stage, enrich_stage, ...])
result_stream = pipeline.run(extractor.run())

# Потребление: здесь реально стартует чтение файла
for result in result_stream:
    ...
```

---

## 🔌 Контракты и границы

### Публичный API

```python
# connector/domain/transform/mapping/__init__.py
from connector.domain.transform.mapping.mapper_core import MapperCore
from connector.domain.transform_dsl.compilers.mapping import MapperDsl
from connector.domain.transform.mapping.mapper_engine import MapperEngine

__all__ = ["MapperCore", "MapperDsl", "MapperEngine"]
```

Delivery и stages импортируют из `connector.domain.transform.mapping`, не из подмодулей.

### Запрещённые импорты

```python
# ПРАВИЛЬНО: delivery создаёт конкретный источник
from connector.infra.sources.csv_reader import CsvRecordSource

# ПРАВИЛЬНО: domain работает с Protocol
from connector.domain.ports.transform.sources import RowSource, SourceMapper

# ЗАПРЕЩЕНО: mapper-core не импортирует delivery
# from connector.delivery import ...

# ЗАПРЕЩЕНО: mapper-core не импортирует конкретный источник напрямую
# from connector.infra.sources.csv_reader import CsvRecordSource  # только delivery

# ЗАПРЕЩЕНО: MapStage не знает о конкретном MapperEngine
# from connector.domain.transform.mapping import MapperEngine  # только delivery
```

### Инварианты

| Инвариант | Описание |
|-----------|----------|
| `MapperCore` не бросает исключений | Все ошибки → `DiagnosticItem` в `errors/warnings` |
| `row=None` если хоть одна `ERROR` | `final_row = row if not errors else None` |
| `warnings` не обнуляют `row` | Только `errors` обнуляют |
| `SourceRecord` иммутабелен | Не модифицируется ни в одной стадии |
| MetaRule только при успехе | `if not errors: for meta_rule in compiled.meta:` |
| `row_ref=None` после map | Заполняет normalize-стадия |
| `secret_candidates={}` после map | Заполняет resolve-стадия |

---

## 🛠️ HOW-TO: Добавить новый тип источника

Сейчас реализован только `type: "file"` + `format: "csv"`.
`SourceConfig` объявляет `type: Literal["file", "db", "api"]` — остальные типы
готовы к реализации.

### Шаг 1: Создать ридер

```python
# connector/infra/sources/db_reader.py

from typing import Iterable
from connector.domain.transform.core.source_record import SourceRecord


class DbRecordSource:
    """
    Источник записей из базы данных.
    Реализует RowSource Protocol через __iter__.
    """

    def __init__(self, connection_string: str, query: str) -> None:
        self._connection_string = connection_string
        self._query = query

    def __iter__(self) -> Iterable[SourceRecord]:
        import sqlalchemy
        engine = sqlalchemy.create_engine(self._connection_string)
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(self._query))
            for line_no, row in enumerate(result, start=1):
                values = dict(row._mapping)
                yield SourceRecord(
                    line_no=line_no,
                    record_id=f"line:{line_no}",
                    values=values,
                )
```

`RowSource` Protocol удовлетворяется автоматически — `__iter__` возвращает `Iterable[SourceRecord]`.

### Шаг 2: Обновить SourceConfig (если нужны новые опции)

В `connector/domain/transform_dsl/specs/source.py` тип `"db"` уже объявлен.
Если нужны специфичные опции — добавить в `SourceConfig.options: dict[str, Any]`.
Это schema-less dict, специфичные ключи читаются в ридере.

### Шаг 3: Обновить delivery — dispatch по типу

```python
# connector/delivery/cli/pipeline_registry.py

def _build_source(source_spec: SourceSpec, catalog: ErrorCatalog) -> RowSource:
    source_type = source_spec.source.type
    source_format = source_spec.source.format

    if source_type == "file" and source_format == "csv":
        path = resolve_source_location(source_spec)
        has_header = source_spec.source.options.get("has_header_default", True)
        return CsvRecordSource(path=path, has_header=has_header)

    if source_type == "db":
        conn_str = resolve_source_location(source_spec)
        query = source_spec.source.options.get("query", "SELECT * FROM employees")
        return DbRecordSource(connection_string=conn_str, query=query)

    raise ValueError(f"Unsupported source type: {source_type!r} / format: {source_format!r}")
```

### Шаг 4: Обновить YAML

```yaml
# datasets/employees/source_2/source.yaml
dataset: employees
source:
  type: db
  location_ref: EMPLOYEES_DB_URL   # "postgresql://user:pass@host/db"
  options:
    query: "SELECT * FROM employees WHERE active = true"
  fields:
    - name: raw_id
      type: string
      required: true
```

### Шаг 5: Написать тесты

```python
# tests/unit/infra/test_db_reader.py

import pytest
from unittest.mock import patch, MagicMock
from connector.infra.sources.db_reader import DbRecordSource


def test_db_reader_yields_source_records():
    mock_row = MagicMock()
    mock_row._mapping = {"raw_id": "u-001", "full_name": "Иванов Иван"}

    with patch("sqlalchemy.create_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = iter([mock_row])
        mock_engine.return_value.connect.return_value = mock_conn

        source = DbRecordSource("postgresql://...", "SELECT * FROM employees")
        records = list(source)

    assert len(records) == 1
    assert records[0].line_no == 1
    assert records[0].values["raw_id"] == "u-001"
```

---

## 💡 Типичные сценарии

### Сценарий 1: Успешный маппинг CSV-записи

```
CSV строка 2: ["u-001", "Doe, John M.", "jdoe", "john.doe@example.com", "+1-555-0100", ...]

CsvRecordSource (has_header=False):
  → SourceRecord(
        line_no=2,
        record_id="line:2",
        values={"col_0": "u-001", "col_1": "Doe, John M.", "col_2": "jdoe", ...}
    )

Extractor.run():
  → TransformResult(record=..., row=None, errors=())

MapStage → MapperEngine.map(record):
  → MapperCore._apply_rules(record):

    rule: target=personnel_number, source=raw_id, op=copy
      _read_source("raw_id") → "raw_id" not in values → source_index["raw_id"]=0
        → "col_0" in values → return ("u-001", True)
      copy("u-001") → "u-001"
      row["personnel_number"] = "u-001"

    rule: targets=[last_name, first_name, middle_name], source=full_name, op=split_name
      _read_source("full_name") → col_1 → "Doe, John M."
      split_name("Doe, John M.", allow_comma_format=True) → {"last_name": "Doe", "first_name": "John", "middle_name": "M."}
      row["last_name"] = "Doe"
      row["first_name"] = "John"
      row["middle_name"] = "M."

    ... (остальные правила)

    final_row = {"personnel_number": "u-001", "last_name": "Doe", ...}

  → TransformResult(
        record=original_record,
        row={"personnel_number": "u-001", "last_name": "Doe", ...},
        errors=(),
        warnings=(),
        meta={},
    )

NormalizeStage: получает TransformResult с непустым row → нормализует
```

### Сценарий 2: Ошибка в обязательном правиле

```
SourceRecord.values = {"col_0": "u-002", "col_1": "Ivanov", "col_2": "ivanov",
                       "col_3": None, "col_4": None, ...}

rule: targets=[email, phone], sources=[email_or_phone, contacts], op=extract_patterns
  _read_source("email_or_phone") → col_3 → None
  _read_source("contacts")       → col_4 → None
  extract_patterns([None, None], patterns={email: ..., phone: ...}) → {}
  row["email"] = None  (не найдено в dict)
  row["phone"] = None

_validate_schema: "email" in schema.required → _is_present(None) = False
  → DslIssue(ERROR, "REQUIRED_FIELD_MISSING", field="email")
  → errors.append(DiagnosticItem)

final_row = None  (есть errors)
→ TransformResult(row=None, errors=(DiagnosticItem(email required),), ...)

MapStage: пробрасывает с row=None
NormalizeStage: collected.errors → yield без обработки
```

### Сценарий 3: Позиционный CSV без заголовка

```
employees/source_2/source.yaml:
  options:
    has_header_default: false

employees/source_2/mapping.yaml:
  source_columns: [raw_id, full_name, login, email_or_phone, contacts, ...]

CSV-файл:
  u-001,Иванов Иван Петрович,ivan.iv,ivan@company.ru,+7-999-123-45-67,...

CsvRecordSource (has_header=False):
  line_no=1, values={"col_0": "u-001", "col_1": "Иванов Иван Петрович", ...}

MapperCore._source_index:
  {"raw_id": 0, "full_name": 1, "login": 2, "email_or_phone": 3, ...}

rule: target=personnel_number, source=raw_id
  _read_source("raw_id"):
    "raw_id" not in {"col_0": ..., "col_1": ..., ...}
    source_index["raw_id"] = 0 → "col_0" in values → "u-001"
  row["personnel_number"] = "u-001"
```

### Сценарий 4: Ошибка источника — битый файл

```
CsvRecordSource (итерируем):
  строка 1: ["u-001", "Иванов", "ivan"]         → OK, SourceRecord
  строка 2: ["u-002", "Петров"]                  → ожидалось 3 колонки, есть 2
    → CsvFormatError("Invalid column count at line 2: expected 3, got 2")

Extractor.run():
  except Exception as exc:
    yield TransformResult(
        record=SourceRecord(line_no=0, record_id="source", values={}),
        row=None,
        errors=(DiagnosticItem(code="SOURCE_ERROR", message="Invalid column count..."),)
    )
  → итерация завершается (один результат с ошибкой)

MapStage: collected.errors → yield с row=None → pipeline видит одну failed запись
```

### Сценарий 5: on_error="warn" — мягкая обработка

```
rule: target=position, source=employment, op=regex_extract, on_error="warn"
  employment = "rank=Senior"  # нет "role=..."
  regex_extract(pattern="role\\s*[:=]\\s*([^;]+)", group=1) → None (нет совпадения)
  DslIssue(WARN или None — нет match не является ошибкой, row[position] = None)

# Если operation внутри возвращает пустую строку — правило завершается успешно
# с пустым результатом, row["position"] = None
# _is_present(None) = False, но required=False для этого правила
```

---

## 📌 Важные детали

### MappingProxyType: защита meta от мутации

```python
# TransformResult.__post_init__:
object.__setattr__(self, "meta", _freeze_mapping(self.meta))
object.__setattr__(self, "secret_candidates", _freeze_mapping(self.secret_candidates))
```

```python
def _freeze_mapping(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not values:
        return MappingProxyType({})
    if isinstance(values, MappingProxyType):
        return values
    return MappingProxyType(dict(values))
```

После создания `TransformResult` нельзя случайно изменить `meta` или `secret_candidates`
из downstream-стадий. Попытка `result.meta["key"] = value` → `TypeError`.

### row_ref=None после map и его роль

`MapperCore.map_record()` ставит `row_ref=None`. Это означает: в `DiagnosticItem`,
созданных в MAP-стадии, `row_ref` будет построен через `_row_ref_from_record(record)`:

```python
def _row_ref_from_record(record: SourceRecord) -> RowRef:
    return RowRef(
        line_no=record.line_no,
        row_id=record.record_id,
        identity_primary=None,
        identity_value=None,
    )
```

Normalize-стадия заполняет `result.row_ref` полноценным `RowRef` с identity-полями
(personnel_number и т.д.). До normalize `identity_primary` и `identity_value` — None.

### MapStage: meta merge

```python
# Приоритет: MAP перезаписывает EXTRACT при одинаковых ключах
builder.meta = {**collected.meta, **builder.meta}
```

Если `Extractor` установил `meta["source"] = "extractor"`, а `MapperCore` через MetaRule
установил `meta["source"] = "csv"`, в итоге будет `"csv"` (MAP приоритетнее).

### Lazy pipeline и порядок исполнения

```
pipeline.run(extractor.run()) → lazy итератор (файл ещё не открыт)

for result in pipeline.run(extractor.run()):
    # Здесь срабатывает:
    # 1. CsvRecordSource открывает файл и читает строку 1
    # 2. Extractor возвращает TransformResult[None]
    # 3. MapStage вызывает mapper.map() для строки 1
    # 4. NormalizeStage обрабатывает результат
    # → result готов для обработки
    process(result)
    # Далее строка 2, 3, ...
```

### TransformationEngine.apply_ops() — цепочка операций

```python
# connector/domain/dsl/helpers.py
def apply_ops(engine, value, ops) -> tuple[Any, list[DslIssue]]:
    current = value
    all_issues = []
    for op_call in ops:
        func = engine.registry.get(op_call.op)
        result, issues = func(current, **op_call.args)
        all_issues.extend(issues)
        if any(issue.severity == DslSeverity.ERROR for issue in issues):
            break  # остановка при ошибке в цепочке
        current = result
    return current, all_issues
```

Цепочка прерывается при первой ERROR. Все issues собираются и возвращаются в `MapperCore`.

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_mapping_dsl.py` | `MapperEngine.from_dataset()`, полный маппинг записи с реальными данными, отсутствующие колонки, compile validation |
| `tests/unit/transform/test_source_mapper.py` | `MapperEngine.map()` — success path, `row_ref=None`, `secret_candidates={}`, мягкие warnings |
| `tests/unit/transform/test_source_spec.py` | `SourceSpec` загрузка, `resolve_source_location` с env/fallback |
| `tests/unit/mapping/test_mapping_report.py` | Диагностические отчёты после маппинга |

**Пример теста (из `test_mapping_dsl.py`):**

```python
def test_employees_dsl_mapper_maps_record() -> None:
    catalog = build_catalog("employees", strict=True)
    mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
    record = SourceRecord(
        line_no=1, record_id="line:1",
        values={
            "raw_id": "u-001",
            "full_name": "Doe, John M.",
            "login": "jdoe",
            "email_or_phone": "john.doe@example.com",
            "contacts": "+1-202-555-0100",
            "manager": "manager: 42",
            "flags": "disabled=false",
            "employment": "role=Engineer",
            "extra": "password=secret;org_id=77;tab=TAB-01",
        },
    )
    result = mapper.map(record)

    assert result.row is not None
    assert result.row["personnel_number"] == "u-001"
    assert result.row["last_name"] == "Doe"
    assert result.row["first_name"] == "John"
    assert result.row["middle_name"] == "M."
    assert result.row["email"] == "john.doe@example.com"
    assert result.row["manager_id"] == "42"
    assert result.row["is_logon_disable"] == "false"
    assert result.row["position"] == "Engineer"
    assert result.row["organization_id"] == "77"
    assert result.row["avatar_id"] is None
    assert result.errors == ()
    assert result.row_ref is None
    assert result.secret_candidates == {}
```

---

## ❓ FAQ

**Почему `row=None`, а не частичный результат при ошибке?**

Намеренный fail-fast: downstream-стадии (normalize, enrich, match) не умеют работать
с неполными строками. Если email пустой — нет смысла нормализовать и обогащать строку
без ключевого поля. Проверка `if collected.errors: yield with row=None; continue`
позволяет каждой стадии быстро пропустить сломанные записи.

**Как meta отличается от row?**

- `row` — бизнес-данные, которые передаются в целевую систему (email, last_name, ...)
- `meta` — системные метаданные: тип источника, ссылки, вспомогательные индексы
  для resolver/matcher. `meta` не попадает в payload для Ankey REST API.

**Что происходит если `ops` возвращает `None` (не нашло совпадение в regex)?**

`None` записывается в `row[target] = None`. Если поле `required: true` или в `schema.required` —
добавляется `REQUIRED_FIELD_MISSING` и в итоге `row = None`.
Если поле не обязательное — `None` остаётся в `row` и передаётся дальше.

**Может ли один MappingRule писать в несколько полей?**

Да, через `targets: [field1, field2, field3]`. Операция должна возвращать:
- `dict` — каждое target получит `value.get(target)` (split_name)
- `list/tuple` — позиционно: targets[0] = value[0], targets[1] = value[1] (extract_patterns)
- одиночное значение — все targets получат одинаковое значение

**Может ли маппер изменить meta из Extractor?**

Нет мутации. `MapStage` создаёт новый dict через merge:
`{**collected.meta, **builder.meta}`. MAP-значения перезаписывают EXTRACT
при совпадении ключей. Исходный `collected.meta` (MappingProxyType) не изменяется.

**Как работает `diagnostic_boundary` в MapStage?**

`diagnostic_boundary` — context manager, перехватывающий необработанные исключения
внутри `mapper.map()` (не `DslIssue`). Если в MapperCore внезапно выброшен `AttributeError`
или `KeyError` — он будет поймал и сконвертирован в `DiagnosticItem(stage=MAP)`,
`mapped = None`, и запись пройдёт с `row=None`.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [mapper-dsl.md](mapper-dsl.md) | DSL-спецификации: SourceSpec, MappingSpec, SinkSpec, компилятор |
| [docs/dev/layers/dsl/dsl-engine.md](../dsl/dsl-engine.md) | TransformationEngine, операции, OperationRegistry |
| `connector/domain/transform/core/result.py` | TransformResult, TransformResultBuilder |
| `connector/domain/transform/core/source_record.py` | SourceRecord |
| `connector/domain/transform/stages/stages.py` | MapStage, PipelineOrchestrator и все стадии |
| `connector/infra/sources/csv_reader.py` | CsvRecordSource |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — core и инфра mapper-слоя | xORex-LC |
| 2026-05-05 | Обновлены примеры source/mapping файлов под текущий `employees/source_2` contract | xORex-LC |
