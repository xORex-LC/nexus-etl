# Normalizer Core — логика нормализации полей TransformResult

> NormalizerCore принимает `TransformResult` после mapper-стадии и последовательно применяет цепочки операций нормализации к полям `row`: приводит типы, форматирует строки, валидирует результат против sink-схемы и передаёт нормализованную запись в EnrichStage.

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

`NormalizerCore` — центральный исполнитель нормализации. Получает `TransformResult`
после маппинга (строка уже разбита по полям, но типы не приведены) и применяет
к каждому полю цепочку операций из `CompiledNormalizeRules`.

**Полный путь данных через normalize:**

```
MapStage → TransformResult[Mapping[str, Any]]
                    │
                    ▼
          NormalizeStage.run()
                    │
                    ├── records с errors → пропускаются (pass-through)
                    │
                    └── NormalizerEngine.normalize()
                              │
                              ▼
                      NormalizerCore.normalize()
                              │
                              ├── for rule in compiled.rules:
                              │     value = row[rule.field]
                              │     result = apply_ops(engine, value, rule.ops)
                              │     row[rule.field] = result
                              │
                              ├── validate_sink_row/fields (если sink_spec)
                              │
                              └── if errors: row=None
                                  else: row=normalized_dict
                                  │
                                  ▼
                      TransformResult[Mapping[str, Any]]
                                  │
                                  ▼
                         EnrichStage.run()
```

**Что нормализация сохраняет без изменений:**

| Поле `TransformResult` | Поведение в normalize |
|------------------------|-----------------------|
| `record` | Не изменяется (иммутабельный `SourceRecord`) |
| `row` | Изменяется: поля приводятся к нужным типам |
| `row_ref` | Сохраняется как есть (всегда `None` на этом этапе) |
| `match_key` | Сохраняется как есть (всегда `None` на этом этапе) |
| `meta` | Сохраняется без изменений |
| `secret_candidates` | Сохраняется без изменений (не трогается) |
| `errors` | Накапливаются: `(*source.errors, *new_errors)` |
| `warnings` | Накапливаются: `(*source.warnings, *new_warnings)` |

---

## 🏗️ Архитектура слоя

```
NormalizeStage (pipeline stage)
    │
    └── NormalizerEngine (DSL-обвязка)
              │
              ├── NormalizerDsl.compile(spec) → CompiledNormalizeRules
              │
              └── NormalizerCore (исполнитель)
                        │
                        ├── TransformationEngine (apply_ops)
                        │       └── OperationRegistry (26 ops)
                        │
                        ├── sink_spec (для validate_sink_row/fields)
                        │
                        └── CompiledNormalizeRules
                                ├── rules: tuple[NormalizeRule, ...]
                                ├── on_error: str
                                └── options: NormalizeDslBuildOptions
```

| Компонент | Слой | Ответственность |
|-----------|------|-----------------|
| `NormalizeStage` | `domain/transform/stages` | Стадия pipeline: итерация + diagnostic_boundary |
| `NormalizerEngine` | `domain/transform/normalize` | DSL-обвязка: загрузка specs, создание Core |
| `NormalizerCore` | `domain/transform/normalize` | Применение правил к `TransformResult` |
| `CompiledNormalizeRules` | `domain/transform_dsl/compilers` | Frozen правила после компиляции |
| `TransformationEngine` | `domain/dsl` | Движок применения op-цепочек |
| `validate_sink_row` | `domain/transform/common` | Проверка строки против sink-схемы |
| `validate_sink_fields` | `domain/transform/common` | Проверка только затронутых полей |

---

## 🔑 Ключевые абстракции

### NormalizerCore

**Файл:** `connector/domain/transform/normalizer/normalizer_core.py`

```python
class NormalizerCore(Generic[T]):
    def __init__(
        self,
        compiled: CompiledNormalizeRules,
        *,
        engine: TransformationEngine,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder[T] | None = None,
    ) -> None
```

| Параметр | Описание |
|----------|----------|
| `compiled` | Frozen правила из `NormalizerDsl.compile()` |
| `engine` | `TransformationEngine.with_core_ops()` — движок операций |
| `catalog` | `ErrorCatalog` — каталог диагностических кодов |
| `sink_spec` | `SinkSpec | None` — для post-rule валидации строки |
| `row_builder` | `Callable[[dict], T] | None` — фабрика для создания output-объекта |

**`row_builder`** позволяет конвертировать `dict` в dataclass или другой тип.
Если `None` — возвращается `dict` как есть. Поддерживает:
- `Callable(dict) → T`
- `type` являющийся `dataclass` → `T(**normalized_values)` (через `is_dataclass`)

### NormalizerEngine

**Файл:** `connector/domain/transform/normalizer/normalizer_engine.py`

```python
class NormalizerEngine:
    def __init__(
        self,
        spec: NormalizeSpec,
        *,
        catalog: ErrorCatalog,
        dsl: NormalizerDsl | None = None,
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> None

    @classmethod
    def from_dataset(
        cls,
        *,
        dataset: str,
        catalog: ErrorCatalog,
        engine: TransformationEngine | None = None,
        row_builder: RowBuilder | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> "NormalizerEngine"

    def normalize(self, source: TransformResult[Any]) -> TransformResult[Any]
```

`from_dataset()` — стандартная точка входа для production-кода:

```python
NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)
# Внутри:
# 1. load_normalize_spec_for_dataset("employees")   → NormalizeSpec
# 2. load_sink_spec_for_dataset("employees")        → SinkSpec
# 3. load_normalize_build_options_for_dataset(...)  → NormalizeDslBuildOptions
# 4. NormalizerDsl(engine=..., options=...).compile(spec) → CompiledNormalizeRules
# 5. NormalizerCore(compiled, engine=..., catalog=..., sink_spec=...)
```

Параметры `engine` и `options` — тестовые/миграционные хуки: позволяют
инжектировать кастомный движок или options без изменения `registry.yml`.

### NormalizeStage

**Файл:** `connector/domain/transform/stages/stages.py`

Стадия pipeline: оборачивает `NormalizerEngine` в генератор с `diagnostic_boundary`.

```python
class NormalizeStage:
    def __init__(self, normalizer: NormalizerEngine, catalog: ErrorCatalog) -> None
    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]
```

Ключевое поведение: если у входящей записи уже есть `errors` — пропускает нормализацию
(pass-through). Это отличает её от EnrichStage, который делегирует это решение EnricherCore.

---

## 🗂️ Модели данных

### TransformResult — до и после normalize

**Файл:** `connector/domain/transform/core/result.py`

```python
@dataclass(frozen=True, slots=True)
class TransformResult(Generic[T]):
    record: SourceRecord
    row: T | None
    row_ref: RowRef | None
    match_key: MatchKey | None
    meta: Mapping[str, Any]
    secret_candidates: Mapping[str, str]
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
```

**После mapper (вход в normalize):**

```python
TransformResult(
    record=SourceRecord(line_no=2, record_id="line:2", values={...}),
    row={
        "personnel_number": "u-001",
        "last_name": "  Doe  ",          # строка с пробелами
        "first_name": "John",
        "email": "  JOHN@EX.COM  ",      # строка с пробелами и uppercase
        "is_logon_disable": "false",     # строка, а не bool
        "organization_id": "77",         # строка, а не int
        "password": "secret",
        "phone": "+1-202-555-0100",
    },
    row_ref=None,          # ← не задан (устанавливает match-стадия)
    match_key=None,        # ← не задан (устанавливает enrich-стадия)
    meta={},
    secret_candidates={},
    errors=(),
    warnings=(),
)
```

**После normalize (выход в enrich):**

```python
TransformResult(
    record=SourceRecord(line_no=2, ...),  # неизменён
    row={
        "personnel_number": "u-001",      # trim → без изменений (нет пробелов)
        "last_name": "Doe",               # trim убрал пробелы
        "first_name": "John",
        "email": "JOHN@EX.COM",           # trim убрал пробелы
        "is_logon_disable": False,        # to_bool: "false" → False
        "organization_id": 77,            # int_if_digits: "77" → 77
        "password": "secret",             # trim → без изменений
        "phone": "+1-202-555-0100",
    },
    row_ref=None,          # всё ещё None — normalize не устанавливает
    match_key=None,
    meta={},
    secret_candidates={},  # не изменён — не задача normalize
    errors=(),             # если нормализация прошла без ошибок
    warnings=(),
)
```

### MappingProxyType в TransformResult

`meta` и `secret_candidates` оборачиваются в `MappingProxyType` в `__post_init__`
`TransformResult`. Это защита от случайной мутации downstream.

`NormalizerCore.normalize()` явно сохраняет `source.meta` и `source.secret_candidates`
в новый `TransformResult` — таким образом иммутабельность сохраняется.

### DiagnosticItem и DiagnosticStage

**Файл:** `connector/domain/diagnostics/items.py`

При ошибке в нормализации создаётся `DiagnosticItem` с `stage=DiagnosticStage.NORMALIZE`.
Используется `append_dsl_issue()` из `connector/domain/dsl/diagnostics.py`:

```python
def _append_issue(
    errors: list[DiagnosticItem],
    warnings: list[DiagnosticItem],
    rule: NormalizeRule | None,
    source: TransformResult[Any],
    issue: DslIssue,
    on_error: str | None = None,
) -> None:
    effective_on_error = (
        on_error if on_error is not None
        else (rule.on_error if rule else "error")
    )
    append_dsl_issue(
        errors=errors,
        warnings=warnings,
        stage=DiagnosticStage.NORMALIZE,
        issue=issue,
        catalog=self.catalog,
        record_ref=source.row_ref,
        on_error=effective_on_error,
    )
```

`on_error` логика:
- Явный `on_error` (для sink-валидации без конкретного правила) → использует `compiled.on_error`
- Правило задано → использует `rule.on_error`
- `"error"` → `DiagnosticItem` в `errors` → в итоге `row=None`
- `"warn"` → `DiagnosticItem` в `warnings` → строка продолжает строиться

### EngineResult

**Файл:** `connector/domain/dsl/engine.py`

Результат `TransformationEngine.apply()`:

```python
@dataclass(frozen=True)
class EngineResult:
    value: Any
    issues: tuple[DslIssue, ...]
```

`DslIssue.code` варианты при нормализации:

| Код | Когда возникает |
|-----|----------------|
| `"DSL_OP_FAILED"` | Исключение внутри op-функции (напр. `to_bool("xyz")`) |
| `"DSL_OP_UNKNOWN"` | Op не найдена в реестре (при `fail_on_unknown_ops=False` — runtime-check) |
| `"SINK_REQUIRED_MISSING"` | Обязательное поле absent или None в sink-валидации |
| `"SINK_TYPE_INVALID"` | Несоответствие типа в sink-валидации |

---

## 📊 Ключевые методы и алгоритмы

### `NormalizerCore.normalize(source)` — полный алгоритм

**Файл:** `connector/domain/transform/normalizer/normalizer_core.py`

```python
def normalize(self, source: TransformResult[Any]) -> TransformResult[T]:
```

**Шаг 0: Ранняя проверка `row`**

```python
if source.row is None:
    return TransformResult(
        record=source.record,
        row=None,              # ← сохраняем None
        row_ref=source.row_ref,
        match_key=source.match_key,
        meta=source.meta,
        secret_candidates=source.secret_candidates,
        errors=source.errors,
        warnings=source.warnings,
    )
```

Если `row=None` — запись уже помечена как невалидная предыдущими стадиями.
`NormalizerCore` не трогает такую запись — pass-through с сохранением всех полей.

**Шаг 1: Конвертация `row` в mutable dict**

```python
source_values = to_mapping(source.row)
if source_values is None:
    return TransformResult(..., row=None, ...)
```

`to_mapping()` — утилита конвертации: `Mapping → dict`, `dataclass → dict(fields)`.
Если тип не поддерживается — `None` → проброс с `row=None`.

```python
normalized_values: dict[str, Any] = dict(source_values)  # mutable copy
touched_fields: set[str] = set()
errors: list[DiagnosticItem] = []
warnings: list[DiagnosticItem] = []
```

**Шаг 2: Применение правил**

```python
for rule in self.compiled.rules:
    value = normalized_values.get(rule.field)   # текущее значение поля
    if not rule.ops:
        continue                                 # пустые ops — пропустить
    touched_fields.add(rule.field)

    resolved, op_issues = apply_ops(self.engine, value, rule.ops)

    for issue in op_issues:
        self._append_issue(errors, warnings, rule, source, issue)

    normalized_values[rule.field] = resolved    # ← записываем результат всегда
```

Ключевые детали:
- `apply_ops()` останавливает цепочку при первой ошибке. Следующие ops не выполняются.
- `normalized_values[rule.field] = resolved` выполняется **всегда** — даже при ошибке
  (resolved будет последним успешным промежуточным значением). Если ошибка есть,
  финальный `row` будет `None`.
- Поле `touched_fields` накапливает имена полей, к которым применялись правила —
  используется при `validate_only_touched_fields=True`.
- Если поле отсутствует в `normalized_values` — `get()` вернёт `None`.
  Op вызывается с `None`. Большинство ops возвращают `None` для `None`-входа.

**Шаг 3: Sink-валидация**

```python
if self.sink_spec is not None:
    if self.options.validate_only_touched_fields:
        issues = validate_sink_fields(
            normalized_values,
            self.sink_spec,
            fields=touched_fields,       # только затронутые поля
            check_types=True,
        )
    else:
        issues = validate_sink_row(
            normalized_values,
            self.sink_spec,
            check_types=True,            # ← проверяем типы!
        )
    for issue in issues:
        self._append_issue(
            errors, warnings, rule=None, source=source,
            issue=issue,
            on_error=self.compiled.on_error,  # on_error из NormalizeBlock
        )
```

**Ключевое отличие от mapper:** В mapper `validate_sink_row` вызывается с
`check_types=False` (типы ещё строки). В normalize — `check_types=True`,
поскольку типы уже должны быть приведены правилами нормализации.

**Шаг 4: Сборка результата**

```python
if errors:
    row = None                          # ← есть ошибки → row=None
elif self.row_builder is None:
    row = normalized_values             # ← plain dict
elif isinstance(self.row_builder, type) and is_dataclass(self.row_builder):
    row = self.row_builder(**normalized_values)  # ← dataclass(**fields)
else:
    row = self.row_builder(normalized_values)    # ← callable(dict)

return TransformResult(
    record=source.record,
    row=row,
    row_ref=source.row_ref,
    match_key=source.match_key,
    meta=source.meta,
    secret_candidates=source.secret_candidates,
    errors=(*source.errors, *errors),   # ← накапливаем ошибки
    warnings=(*source.warnings, *warnings),
)
```

### Фильтрация записей в NormalizerCore

Normalizer не удаляет записи из потока — он устанавливает `row=None` для записей,
которые не могут быть нормализованы. Downstream-стадии (enrich, match, resolve)
проверяют `collected.errors` и пропускают такие записи.

```
TransformResult(row=None, errors=[...])  → enrich видит errors → pass-through
TransformResult(row={...}, errors=())   → enrich обрабатывает
```

**Уровни фильтрации:**

```
Уровень 1: source.row is None
    → Запись пришла с row=None из предыдущей стадии
    → Немедленный pass-through, normalize не вызывается
    → Все поля (meta, errors, warnings) сохраняются

Уровень 2: to_mapping(source.row) is None
    → row не конвертируется в dict
    → row=None, все поля сохраняются

Уровень 3: ошибки в правилах нормализации (on_error="error")
    → DSL_OP_FAILED / DSL_OP_UNKNOWN / SINK_REQUIRED_MISSING / SINK_TYPE_INVALID
    → DiagnosticItem добавляется в errors
    → После обработки всех правил: if errors → row=None

Уровень 4: предупреждения (on_error="warn")
    → DiagnosticItem добавляется в warnings (не в errors)
    → row НЕ обнуляется — запись продолжает путь
```

### Фильтрация в NormalizeStage

**Файл:** `connector/domain/transform/stages/stages.py`

```python
def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
    for collected in source:
        if collected.errors:          # ← Уже есть ошибки из предыдущих стадий
            yield collected           # ← Pass-through без нормализации
            continue

        boundary_errors: list = []
        normalized: TransformResult | None = None

        with diagnostic_boundary(
            stage=DiagnosticStage.NORMALIZE,
            catalog=self.catalog,
            sink=boundary_errors,
            record_ref=collected.row_ref,
        ):
            normalized = self.normalizer.normalize(collected)

        if normalized is None:        # ← Неожиданное исключение в normalize
            builder = collected.as_builder()
            builder.set_row(None)
            for err in boundary_errors:
                builder.add_error_item(err)
            yield builder.build()
            continue

        builder = normalized.as_builder()
        for err in boundary_errors:
            builder.add_error_item(err)
        yield builder.build()
```

**`collected.errors` check:** Если запись уже имеет ошибки (из map-стадии) —
нормализация не вызывается. Запись пробрасывается as-is. Это ключевой паттерн:
`row=None` с errors означает «не обрабатывать downstream».

**`diagnostic_boundary`:** Перехватывает неожиданные исключения (Python exceptions,
не `DslIssue`) из `NormalizerEngine.normalize()`. Если `normalized = None` после
boundary — добавляет диагностику в errors и выдаёт `row=None`.

### Sink-валидация: `validate_sink_row` vs `validate_sink_fields`

**Файл:** `connector/domain/transform/common/sink_validation.py`

**`validate_sink_row(row, spec, check_types)`** — проверяет всю строку:

```python
for field in spec.sink.fields:
    _validate_field(row, field, check_types, issues)
```

Проверяет только поля из `spec.sink.fields` (не `system_fields` — они генерируются runtime).

**`validate_sink_fields(row, spec, fields, check_types)`** — проверяет только перечисленные поля:

```python
indexed = {f.name: f for f in (*spec.sink.fields, *spec.sink.system_fields)}
for name in fields:
    field = indexed.get(name)
    if field is None:
        continue   # Поле не в sink → пропустить
    _validate_field(row, field, check_types, issues)
```

Используется при `validate_only_touched_fields=True`.

**`_validate_field` — детальная логика:**

```python
def _validate_field(row, field, check_types, issues):
    name = field.name
    has_key = name in row
    value = row.get(name)

    if field.required:
        if not has_key:
            issues.append(SINK_REQUIRED_MISSING)   # отсутствует ключ
            return
        if value is None and not field.nullable:
            issues.append(SINK_REQUIRED_MISSING)   # ключ есть, значение None
            return
        if isinstance(value, str) and value.strip() == "" and not field.nullable:
            issues.append(SINK_REQUIRED_MISSING)   # пустая строка
            return

    if not check_types:
        return   # без type-check возвращаем

    if value is None:
        return   # None допустим (выше проверили nullable)

    if not _matches_type(value, field.type):
        issues.append(SINK_TYPE_INVALID)
```

**Поддерживаемые типы в sink-схеме:**

| `field.type` | Python-тип | Дополнительно |
|--------------|-----------|---------------|
| `"string"` | `str` | |
| `"bool"` | `bool` | Или `str` в `{"true","false","1","0","yes","no","y","n"}` |
| `"int"` | `int` | Или строка-цифры; `bool` → `False` |
| `"float"` | `float` | Или `int`; `bool` → `False` |
| `"object"` | `Mapping` | Любое `Mapping` |
| `"list"` | `list` | |
| Другое | Любое | `True` — тип не проверяется |

---

## 🔄 Взаимодействие с другими слоями

### Позиция в pipeline

```
Extractor.run()
      ↓ TransformResult(row=None или row=dict из csv-записи)
MapStage.run()
      ↓ TransformResult(row={"personnel_number": "u-001", "is_logon_disable": "false", ...})
NormalizeStage.run()
      ↓ TransformResult(row={"personnel_number": "u-001", "is_logon_disable": False, ...})
EnrichStage.run()
      ↓ TransformResult(row={...}, match_key=MatchKey("Doe|John|..."))
MatchStage.run()
      ↓ TransformResult(row_ref=RowRef(...))
ResolveStage.run()
```

**Что получает EnrichStage:**
- `row` — нормализованный dict с Python-типами (`bool`, `int`, строки без пробелов)
- `row_ref` — всё ещё `None` (устанавливает MatchStage)
- `match_key` — всё ещё `None` (устанавливает EnrichStage)
- `secret_candidates` — пустой dict `{}` (заполняется в ResolveStage)
- `errors + warnings` — накопленные из map + normalize

### Сборка в delivery

```python
# Создание стадии один раз при старте команды
normalizer = NormalizerEngine.from_dataset(dataset="employees", catalog=catalog)
normalize_stage = NormalizeStage(normalizer=normalizer, catalog=catalog)

# Подключение в PipelineOrchestrator
pipeline = PipelineOrchestrator([
    map_stage,
    normalize_stage,    # ← вторая стадия
    enrich_stage,
    match_stage,
    resolve_stage,
])
```

Нет глобального состояния — `NormalizerCore` безопасен для последовательного
вызова с разными записями.

### Lazy pipeline

`NormalizeStage.run()` — генератор. Данные не материализуются:

```
NormalizeStage.run(source)        # Создаёт генератор
    ↓ next()                      # Запрос от EnrichStage
    → MapStage.run(...)           # Запрашивает следующую mapped запись
    → NormalizerCore.normalize()  # Нормализует её
    → yield TransformResult       # Отдаёт EnrichStage
```

---

## 🔌 Контракты и границы

**Normalizer-пакет** (`connector/domain/transform/normalizer/`) содержит только:
- `NormalizerCore` — исполнитель правил
- `NormalizerEngine` — DSL-обвязка (загрузка specs, создание Core)

**Запрещённые импорты в normalizer-пакете:**
- `connector/infra/` — никакой инфраструктуры (CSV, DB, httpx)
- `connector/delivery/` — никакой доставки
- `connector/domain/transform/enrich/` — нет зависимости вперёд по pipeline
- `connector/domain/transform/stages/` — нет обратной зависимости

**Зависимости normalizer-core (что можно импортировать):**
- `connector/domain/dsl/` — `TransformationEngine`, `apply_ops`, `DslIssue`
- `connector/domain/transform/core/` — `TransformResult`, `DiagnosticItem`
- `connector/domain/transform_dsl/` — `CompiledNormalizeRules`, `NormalizerDsl`
- `connector/domain/diagnostics/` — `ErrorCatalog`, `DiagnosticStage`
- `connector/domain/transform/common/` — `validate_sink_row`, `validate_sink_fields`

**Нарушения изоляции:**

| ❌ Нарушение | ✅ Правильно |
|-------------|-------------|
| Импорт `CsvReader` в `normalizer_core.py` | Ридер создаётся в delivery, передаётся как SourceRecord |
| Изменять `source.meta` напрямую | Создавать новый `TransformResult` с обновлёнными полями |
| Хранить состояние между вызовами `normalize()` | `NormalizerCore` stateless — нет mutable полей |
| Импорт `EnricherCore` или `MatchCore` | Только downstream pipeline видит normalizer, не наоборот |

---

## 🛠️ HOW-TO

### Добавить нормализацию нового поля в датасет

1. Убедиться что поле есть в `employees/source_2/mapping.yaml` (задан target)
2. Открыть `datasets/employees.normalize.yaml`:

```yaml
normalize:
  on_error: warn
  rules:
    # ... существующие правила ...

    - field: department_code     # ← новое поле
      ops:
        - op: trim
        - op: upper
```

3. Проверить что поле описано в `datasets/employees.sink.yaml` (тип, required, nullable)
4. Запустить тесты: `pytest tests/ -k employees`

---

### Добавить нормализацию с валидацией типа

Если поле должно стать `bool` и sink-схема это ожидает:

```yaml
# employees.sink.yaml:
sink:
  fields:
    - name: is_blocked
      type: bool
      required: false
      nullable: true

# employees.normalize.yaml:
rules:
  - field: is_blocked
    op: parse_bool
    args:
      true_values: ["1", "yes", "true"]
      false_values: ["0", "no", "false"]
    on_error: warn   # warn → запись не блокируется при null/нестандартном значении
```

После нормализации `validate_sink_row(check_types=True)` проверит что `is_blocked`
действительно `bool` или `None` (nullable). Если `parse_bool` вернул `False` (bool) — ok.

---

### Изменить поведение sink-валидации

Через `registry.yml`:

```yaml
# Только проверять поля, затронутые нормализацией:
datasets:
  employees:
    build_options:
      normalize:
        validate_only_touched_fields: true
```

При `validate_only_touched_fields=True` sink-валидация не будет жаловаться на
отсутствующие обязательные поля, которые не затрагиваются правилами normalize.
Это полезно если обязательные поля уже были проверены в mapper-стадии.

---

### Дебаггинг: отследить что происходит с полем

Если запись получает `row=None` и непонятно почему:

1. Проверить `result.errors` — каждый `DiagnosticItem` содержит:
   - `code` — `DSL_OP_FAILED` / `SINK_REQUIRED_MISSING` / `SINK_TYPE_INVALID`
   - `message` — что именно пошло не так
   - `field` — имя поля (в sink-ошибках)
   - `stage` — `DiagnosticStage.NORMALIZE`

2. Добавить `on_error: warn` на подозрительное правило (временно) — это покажет
   warning вместо блокировки строки

3. Проверить порядок правил: если `trim` стоит после `to_bool`, то `to_bool`
   получит строку с пробелами → `ValueError`

---

## 💡 Типичные сценарии

### Сценарий 1: Успешная нормализация

```
Вход:
  row={"email": "  John@EX.COM  ", "is_logon_disable": "false", "organization_id": "77"}
  errors=()

NormalizerCore._apply_rules():
  rule{field="email", ops=[trim]}:
    value = "  John@EX.COM  "
    apply_ops → ("John@EX.COM", issues=[])
    normalized_values["email"] = "John@EX.COM"

  rule{field="is_logon_disable", ops=[to_bool]}:
    value = "false"
    apply_ops → (False, issues=[])
    normalized_values["is_logon_disable"] = False

  rule{field="organization_id", ops=[int_if_digits]}:
    value = "77"
    apply_ops → (77, issues=[])
    normalized_values["organization_id"] = 77

validate_sink_row(check_types=True):
  email: str ✓
  is_logon_disable: bool ✓
  organization_id: int ✓
  → issues=[]

errors=[] → row=normalized_values

Выход:
  row={"email": "John@EX.COM", "is_logon_disable": False, "organization_id": 77}
  errors=()
```

---

### Сценарий 2: Ошибка типа (`on_error="error"`)

```
Вход:
  row={"is_logon_disable": "1"}   # источник передал "1"
  errors=()

normalize.yaml:
  - field: is_logon_disable
    op: to_bool
    # on_error: error  ← дефолт

NormalizerCore._apply_rules():
  rule{field="is_logon_disable", ops=[to_bool]}:
    value = "1"
    apply_ops → EngineResult(
        value="1",    # последнее значение до ошибки
        issues=[DslIssue(code="DSL_OP_FAILED", message="Invalid boolean value")]
    )
    _append_issue(on_error="error") → DiagnosticItem в errors

errors=[DiagnosticItem(...)] → row=None

Выход:
  row=None
  errors=(DiagnosticItem(code="DSL_OP_FAILED", stage=NORMALIZE),)
```

---

### Сценарий 3: Предупреждение (`on_error="warn"`)

```
Вход:
  row={"some_int_field": "abc"}
  errors=()

normalize.yaml:
  - field: some_int_field
    op: to_int
    on_error: warn

NormalizerCore._apply_rules():
  apply_ops → EngineResult(value="abc", issues=[DslIssue(DSL_OP_FAILED)])
  _append_issue(on_error="warn") → DiagnosticItem в warnings (не в errors)

Выход:
  row={..., "some_int_field": "abc"}   # значение не конвертировано, строка осталась
  errors=()
  warnings=(DiagnosticItem(code="DSL_OP_FAILED", stage=NORMALIZE),)
```

---

### Сценарий 4: Pass-through для записи с предыдущими ошибками

```
Вход (из MapStage):
  row=None
  errors=(DiagnosticItem(code="missing_source_column", stage=MAP),)

NormalizeStage.run():
  if collected.errors:   # True → pass-through
    yield collected
    continue

Выход (без изменений):
  row=None
  errors=(DiagnosticItem(code="missing_source_column", stage=MAP),)
```

Энрайчер, матчер и резолвер тоже увидят `collected.errors` и пробросят запись дальше.
В итоге `ResultProcessor` запишет её в отчёт как ошибочную.

---

### Сценарий 5: Sink-валидация с `check_types=True`

```
После нормализации:
  row={"is_logon_disable": "false"}   # to_bool не применялся (поле не в правилах)

employees.sink.yaml:
  - name: is_logon_disable
    type: bool
    required: true
    nullable: false

validate_sink_row(row, sink_spec, check_types=True):
  field=is_logon_disable, value="false", expected=bool
  _matches_type("false", "bool"):
    str → value.strip().lower() in {"true","false","1","0","yes","no","y","n"} → True
  → Нет ошибки! (строка "false" считается допустимым bool)
```

`_matches_type` для `bool` допускает строки `"true"/"false"/"1"/"0"` — это
предотвращает ложные ошибки при частичной нормализации.

---

### Сценарий 6: Неожиданное исключение (diagnostic_boundary)

```
NormalizeStage.run():
  with diagnostic_boundary(stage=NORMALIZE, ...) as boundary_errors:
    normalized = self.normalizer.normalize(collected)
    # ↑ Внутри бросается Exception (не DslIssue) — напр. DB-ошибка при row_builder

→ boundary_errors = [DiagnosticItem(code="NORMALIZE_ERROR", ...)]
→ normalized = None (исключение поглощено)

if normalized is None:
    builder = collected.as_builder()
    builder.set_row(None)
    for err in boundary_errors:
        builder.add_error_item(err)
    yield builder.build()
```

`diagnostic_boundary` — safety net для неожиданных исключений.
Pipeline не падает — ошибка фиксируется в диагностике и запись помечается как ошибочная.

---

## 📌 Важные детали

| Деталь | Описание |
|--------|----------|
| `check_types=True` в normalize | Отличие от mapper: типы уже должны быть приведены — проверяем строго |
| Нет rollback | Если правила 1-3 применились, а 4-е упало — `normalized_values` уже изменён. `errors` → `row=None` |
| `row_ref=None` | Normalize не устанавливает `row_ref` — это делает MatchStage на основе `MatchedRow` |
| `match_key=None` | Normalize не устанавливает `match_key` — это делает EnrichStage |
| `secret_candidates={}` | Normalize не детектирует секреты — это задача ResolveStage |
| Порядок важен | Правила применяются в порядке списка. `trim` до `to_bool` — безопасно. `to_bool` до `trim` — `to_bool("  false  ")` может упасть |
| `touched_fields` для validate_only | При `validate_only_touched_fields=True` sink-проверяются только поля с rules |
| Stateless | `NormalizerCore` не хранит состояния между записями — безопасен для последовательного вызова |

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/integration/transform/test_dsl_build_options.py` | Defaults, merge-приоритет, strict mode для `NormalizeDslBuildOptions` |
| `tests/unit/transform/test_pipeline_stage_contract.py` | `NormalizeStage` как участник `PipelineOrchestrator`, `StageContract` протокол |
| `tests/unit/transform/test_stage_factory.py` | Создание `NormalizeStage` через factory |
| `tests/unit/transform/test_dsl_ops.py` | Операции из реестра (shared с normalize) |
| `tests/unit/transform/test_mapping_dsl.py` | End-to-end маппинг + операции (те же ops) |
| `tests/e2e/pipelines/test_pipeline_container_e2e.py` | Полный pipeline включая normalize |
| `tests/integration/delivery/test_pipeline_container.py` | Integration normalize в delivery |

**Покрытие core алгоритмов:** `NormalizerCore._apply_rules()` и
`NormalizerCore.normalize()` тестируются через e2e-тесты pipeline, а не
изолированными unit-тестами. Это намеренный выбор — нормализация тестируется
как часть transform-pipeline на реальных данных.

---

## ❓ FAQ

**Почему `row=None` если только одно правило упало?**

Любая ошибка в нормализации означает что строка в inconsistent-состоянии.
Downstream стадии (enrich, match) рассчитаны на корректные данные — частично
нормализованная строка может привести к непредсказуемым последствиям (напр.
матч по `organization_id="77"` vs `organization_id=77`).

**Что если `trim` применяется к `None`?**

`op_trim(None)` → `_normalize_whitespace(None, empty_to_none=True)` → `return None`.
`normalized_values[field] = None`. Поле остаётся `None` — не ошибка.

**Почему `row_ref=None` после normalize?**

`row_ref` содержит идентификаторы записи в целевой системе (`RowRef.identity_value`).
Эти идентификаторы становятся известны только после стадии матчинга — когда
система нашла соответствующую запись в IDM. До этого `row_ref=None`.

**Может ли normalize изменить `meta`?**

Нет — `meta` из source передаётся без изменений в выходной `TransformResult`.
Meta изменяется только в маппере (через MetaRule) и не в normalize.

**Почему нет отдельного `NormalizeSpec` поля для `source_columns`?**

Normalize работает уже с именованными полями (после mapper). Позиционный
fallback (`col_N`) нужен только mapper-стадии где ещё нет заголовков CSV.

**Что если поле задано в normalize-правилах, но отсутствует в sink?**

При `validate_only_touched_fields=True` — `indexed.get(name)` вернёт `None`,
поле пропускается (не проверяется). При `validate_only_touched_fields=False` —
поле не проверяется (iterate только по `spec.sink.fields`). Ни в том ни в другом
случае ошибки нет.

**Что передаётся следующему слою (EnrichStage)?**

`TransformResult[dict[str, Any]]` с:
- `row` — нормализованный dict (типы приведены, пробелы убраны)
- `row_ref=None` — не задан (будет в match)
- `match_key=None` — не задан (будет в enrich/match)
- `meta` — передан без изменений из mapper
- `secret_candidates={}` — пустой (задача resolve)
- `errors + warnings` — накопленные из всех предыдущих стадий (map + normalize)

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [normalizer-dsl.md](normalizer-dsl.md) | DSL-спецификации: NormalizeSpec, NormalizeRule, 26 операций, compile-политики |
| [mapper-core.md](../mapper/mapper-core.md) | Core-логика mapper (RowSource, CsvRecordSource, MapperCore, TransformResult) |
| [docs/dev/layers/dsl/dsl-engine.md](../dsl/dsl-engine.md) | TransformationEngine, операции, OperationRegistry |
| [docs/dev/layers/enrich/enrich-core.md](../enrich/enrich-core.md) | Следующая стадия: EnricherCore, match_key, CandidateValue |
| `datasets/employees.normalize.yaml` | Эталонный пример normalize-спецификации |
| Активный registry file | Центральный реестр датасетов (`dataset.registry_path` или default `datasets/registry.yml`) |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — core-логика normalizer-слоя | xORex-LC |
| 2026-05-05 | Обновлены примеры bool-нормализации на `parse_bool` и уточнён reference на active registry path | xORex-LC |
