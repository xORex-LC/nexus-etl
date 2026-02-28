# Report Pipeline — Stage Integration and Data Flow

> **Producer model**: each pipeline stage is a producer that feeds `ReportCollector` with per-row results, diagnostics, and context blocks. No stage reads back from the collector — data flows in one direction.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ DiagnosticItem → ReportDiagnostic конвертация](#️-diagnosticitem--reportdiagnostic-конвертация)
- [📊 TransformResultProcessor](#-transformresultprocessor)
  - [Алгоритм process()](#алгоритм-process)
  - [Stage-фильтрация диагностики](#stage-фильтрация-диагностики)
  - [Маскировка секретов в payload](#маскировка-секретов-в-payload)
  - [Отслеживание vault-кандидатов](#отслеживание-vault-кандидатов)
  - [finalize() — сброс статистики в context](#finalize--сброс-статистики-в-context)
- [📊 PlanningResultProcessor](#-planningresultprocessor)
- [📊 EnricherReport](#-enricherreport)
- [📊 ApplyReportPresenter](#-applyreportpresenter)
- [🔄 Context-блоки: кто и что пишет](#-context-блоки-кто-и-что-пишет)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Описать, как каждая стадия ETL-конвейера (transform, enrich, match, resolve, apply, cache) становится производителем данных для отчёта — через адаптеры `TransformResultProcessor`, `PlanningResultProcessor`, `EnricherReport` и `ApplyReportPresenter`.

**Ключевая ответственность**:
- Конвертировать внутренние диагностики конвейера (`DiagnosticItem`) в унифицированный report-формат (`ReportDiagnostic`).
- Адаптировать `TransformResult` (общий результат трансформации строки) к `ReportCollector.add_item()`.
- Фильтровать диагностику по стадии (upstream vs. текущая стадия) для точного атрибутирования ошибок.
- Маскировать секретные поля в payload перед записью в отчёт.
- Заполнять именованные context-блоки от стадий apply, cache, enrich, import и т.д.

**Расположение в кодовой базе**:
- `connector/domain/reporting/diagnostics.py` — конвертация DiagnosticItem → ReportDiagnostic
- `connector/domain/transform/core/result_processor.py` — `TransformResultProcessor`, `PlanningResultProcessor`
- `connector/domain/transform/enrich/report.py` — `EnricherReport`
- `connector/delivery/presenters/apply_report_presenter.py` — `ApplyReportPresenter`
- `connector/delivery/commands/common.py` — `attach_dictionary_report_snapshot_if_available()`
- `connector/common/sanitize.py` — `maskSecretsInObject()`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/
├── domain/
│   ├── reporting/
│   │   └── diagnostics.py                # DiagnosticItem → ReportDiagnostic
│   ├── transform/
│   │   ├── core/
│   │   │   └── result_processor.py       # TransformResultProcessor, PlanningResultProcessor
│   │   └── enrich/
│   │       └── report.py                 # EnricherReport (per-row enrich stats)
│   └── models.py                         # DiagnosticItem, DiagnosticStage
├── common/
│   └── sanitize.py                       # maskSecretsInObject()
└── delivery/
    ├── presenters/
    │   └── apply_report_presenter.py     # ApplyResult → ReportCollector
    └── commands/
        ├── common.py                     # attach_dictionary_report_snapshot_if_available()
        ├── enrich.py                     # context["enrich"] / vault rollout
        └── import_apply.py              # context["apply"]
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Class Diagram](../../../uml/pipeline/report_layer/report_layer_class.puml) | Структура классов и связи |
| Sequence | [Sequence Diagram](../../../uml/pipeline/report_layer/report_layer_sequence.puml) | Поток данных от стадий к collector |
| Activity | [Activity Diagram](../../../uml/pipeline/report_layer/report_layer_activity.puml) | Алгоритм process() |

**PlantUML исходники**: `docs/uml/pipeline/report_layer/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Adapter (Адаптер)

**Где применяется**: `TransformResultProcessor` адаптирует `TransformResult` (внутренний формат конвейера) к интерфейсу `ReportCollector.add_item()`. `ApplyReportPresenter` адаптирует `ApplyResult` к тому же интерфейсу.

**Реализация в коде**:
- **Adaptee**: `TransformResult` в `connector/domain/transform/core/result.py`
- **Adapter**: `TransformResultProcessor` в `connector/domain/transform/core/result_processor.py`
- **Target**: `ReportCollector` в `connector/domain/reporting/collector.py`

**Зачем**: Стадии конвейера не знают о формате отчёта; адаптеры изолируют знание о `ReportCollector` от самих стадий.

---

#### Паттерн 2: Template Method (Шаблонный метод)

**Где применяется**: `PlanningResultProcessor` наследует `TransformResultProcessor` и переопределяет `process()`, добавляя `meta_builder` и `should_skip` поверх базового алгоритма.

**Реализация в коде**:
- **Base**: `TransformResultProcessor.process()` — общая логика (счётчики, payload, store)
- **Override**: `PlanningResultProcessor.process()` — добавляет planning-специфичные meta и skip

**Зачем**: Переиспользует всю инфраструктуру (masking, filtering, storing) без дублирования.

---

#### Паттерн 3: Strategy через Callable

**Где применяется**: `payload_builder: Callable[[TransformResult], Any] | None` в `TransformResultProcessor` — внешняя стратегия построения payload; если не передана, используется `result.row` по умолчанию.

**Зачем**: Разные стадии конвейера имеют разную структуру row; стратегия позволяет извлечь нужное представление без изменения базового адаптера.

### Диаграмма зависимостей

```
Pipeline stages (enrich/match/resolve/apply)
       │ produce
       ▼
TransformResult  ──────────────────────────────────────────────────►
                                                                    │
         TransformResultProcessor.process()                        │
             │                                                      │
             ├── split_report_diagnostics()  ◄─── DiagnosticItem   │
             ├── maskSecretsInObject()                              │
             └── report.add_item()  ─────────────────► ReportCollector
                                                             │
ApplyResult ──► ApplyReportPresenter.present()               │
                   │                                          │
                   ├── report.add_op()  ──────────────────►  │
                   └── collector.items.append()  ──────────► │
                                                             │
Command handlers ──► report.set_context()  ─────────────────►
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `TransformResultProcessor` | Per-row адаптер TransformResult → ReportCollector | `process()`, `finalize()`, `_filter_for_report()` |
| `PlanningResultProcessor` | Адаптер для planning-стадий (match/resolve) | `process()` (override), `meta_builder`, `should_skip` |
| `EnricherReport` | Per-row аккумулятор статистики enrich | `record()`, `as_dict()` |
| `ApplyReportPresenter` | Адаптер ApplyResult → ReportCollector | `present()` |

### Ключевые функции

| Функция | Модуль | Назначение |
|---------|--------|-----------|
| `to_report_diagnostics(errors, warnings)` | `diagnostics.py` | Конвертация DiagnosticItem → ReportDiagnostic, слияние errors+warnings |
| `split_report_diagnostics(errors, warnings)` | `diagnostics.py` | То же, но возвращает раздельные списки (errors, warnings) |
| `maskSecretsInObject(obj)` | `sanitize.py` | Рекурсивная маскировка секретных полей в dict/dataclass |
| `attach_dictionary_report_snapshot_if_available(ctx, report)` | `commands/common.py` | Best-effort snapshot dictionary telemetry в report.context |

---

## 🗂️ DiagnosticItem → ReportDiagnostic конвертация

**Модуль**: `connector/domain/reporting/diagnostics.py`

Внутри конвейера диагностика представлена типом `DiagnosticItem` (domain model из `connector/domain/models.py`). Для сохранения в отчёт она должна быть конвертирована в `ReportDiagnostic`.

### Структура DiagnosticItem (источник)

```python
@dataclass
class DiagnosticItem:
    severity: DiagnosticSeverity    # enum: ERROR | WARNING
    stage: str | DiagnosticStage    # строка или enum
    code: str | None                # машиночитаемый код
    field: str | None               # имя поля
    message: str | None             # человекочитаемое описание
    # + опционально: rule, details (через getattr)
```

### Функции конвертации

**`to_report_diagnostics(errors, warnings) → list[ReportDiagnostic]`**

Принимает оба списка одновременно и возвращает единый список `ReportDiagnostic`. Каждый `DiagnosticItem` конвертируется через `_from_item()`. Уже готовые `ReportDiagnostic`-объекты проходят без изменений.

```python
def to_report_diagnostics(
    errors: Iterable[DiagnosticItem | ReportDiagnostic] | None,
    warnings: Iterable[DiagnosticItem | ReportDiagnostic] | None,
) -> list[ReportDiagnostic]:
    diagnostics = []
    for item in errors or []:
        diagnostics.append(_from_item(item, fallback_severity="error"))
    for item in warnings or []:
        diagnostics.append(_from_item(item, fallback_severity="warning"))
    return diagnostics
```

**`split_report_diagnostics(errors, warnings) → tuple[list, list]`**

Аналогична, но возвращает раздельные `(errors_list, warnings_list)` — используется в `TransformResultProcessor.process()`, который передаёт раздельные списки в `report.add_item()`.

**`_from_item(item, fallback_severity) → ReportDiagnostic`**

Маппинг полей:

| DiagnosticItem поле | → ReportDiagnostic поле | Примечание |
|--------------------|------------------------|-----------|
| `severity.value` | `severity` | `.value` извлекает строку из enum; `fallback_severity` если атрибута нет |
| `stage` | `stage` | передаётся как есть (str или enum.value) |
| `code` | `code` | прямой маппинг |
| `field` | `field` | прямой маппинг |
| `message` | `message` | прямой маппинг |
| `getattr(item, "rule", None)` | `rule` | опциональный атрибут |
| `getattr(item, "details", None)` | `details` | опциональный атрибут |

```python
def _from_item(item: DiagnosticItem | ReportDiagnostic, fallback_severity: str) -> ReportDiagnostic:
    if isinstance(item, ReportDiagnostic):
        return item    # уже в нужном формате — pass-through
    severity = item.severity.value if getattr(item, "severity", None) is not None else fallback_severity
    return ReportDiagnostic(
        severity=severity,
        stage=item.stage,
        code=item.code,
        field=item.field,
        message=item.message,
        rule=getattr(item, "rule", None),
        details=getattr(item, "details", None),
    )
```

---

## 📊 TransformResultProcessor

**Модуль**: `connector/domain/transform/core/result_processor.py`

Центральный per-row адаптер между `TransformResult` (результат одной стадии конвейера) и `ReportCollector`. Создаётся один раз на стадию и используется в цикле по строкам.

### Конструктор

```python
TransformResultProcessor(
    *,
    report: ReportCollector,
    include_items: bool,           # сохранять ли OK-строки в items (True → include all)
    context_key: str,              # ключ для set_context() в finalize()
    ok_label: str,                 # метка для ok-счётчика в context (например "enriched_rows")
    failed_label: str,             # метка для failed-счётчика (например "failed_rows")
    payload_builder: Callable | None = None,  # стратегия извлечения payload
    report_stage: DiagnosticStage | None = None,  # фильтр стадии для диагностики
    include_upstream_diagnostics: bool = False,   # включать ли upstream-диагностику
)
```

**Типичное использование** (стадия enrich):
```python
processor = TransformResultProcessor(
    report=report,
    include_items=include_items_flag,
    context_key="enrich",
    ok_label="enriched_rows",
    failed_label="failed_rows",
    report_stage=DiagnosticStage.ENRICH,
    include_upstream_diagnostics=False,
)

for result in enrich_results:
    processor.process(result)

command_result = processor.finalize()
```

---

### Алгоритм process()

**Сигнатура**:
```python
def process(
    self,
    result: TransformResult | None,
    *,
    row_ref: RowRef | None = None,
    force_failed: bool = False,
    errors_override: list[DiagnosticItem] | None = None,
    warnings_override: list[DiagnosticItem] | None = None,
) -> None:
```

**Алгоритм**:

```
1. rows_total += 1

2. Определить eff_errors, eff_warnings:
   - Если errors_override задан → использовать его
   - Иначе → result.errors (или [] если result=None)
   - Аналогично для warnings_override

3. Определить статус:
   - has_errors = force_failed OR bool(eff_errors)
   - status = "FAILED" if has_errors else "OK"

4. _filter_for_report(errors, warnings):
   - Если report_stage не задан или include_upstream_diagnostics=True:
       вернуть все errors и warnings, upstream_count=0
   - Иначе:
       report_errors = [item for item in errors if item.stage == report_stage]
       upstream_errors_count = len(errors) - len(report_errors)
       (аналогично для warnings)

5. Обновить счётчики:
   - failed_rows += 1 (если has_errors) или ok_rows += 1
   - warnings_rows += 1 (если eff_warnings)

6. Отследить vault-кандидаты (см. раздел ниже)

7. Определить should_store:
   - should_store = (status == "FAILED") OR include_items

8. Разрешить effective_row_ref:
   - row_ref аргумент → result.row_ref → RowRef(line_no, row_id)

9. Построить payload (если should_store и result.row не None):
   - payload_builder(result) или result.row
   - maskSecretsInObject(payload)
   - Замаскировать secret_fields[field] = "***"

10. split_report_diagnostics(eff_errors, eff_warnings)
    → report_errors, report_warnings

11. report.add_item(
        status, row_ref, payload, errors, warnings,
        meta={match_key, secret_candidate_fields,
              upstream_errors_count, upstream_warnings_count},
        store=should_store,
    )
```

**ASCII Flow**:
```
process(result)
    │
    ├─► rows_total += 1
    │
    ├─► resolve effective errors/warnings (override or result)
    │
    ├─► has_errors? ──Yes──► status = "FAILED", failed_rows += 1
    │              └──No───► status = "OK",     ok_rows += 1
    │
    ├─► _filter_for_report()  ──► split by report_stage
    │                              (upstream spillover counted separately)
    │
    ├─► track vault candidates (secret_fields → vault_candidates_rows)
    │
    ├─► should_store = FAILED OR include_items
    │
    ├─► if should_store:
    │       build payload → maskSecretsInObject → mask secret_fields → "***"
    │
    ├─► split_report_diagnostics() → (report_errors, report_warnings)
    │
    └─► report.add_item(status, row_ref, payload, errors, warnings, meta, store)
```

---

### Stage-фильтрация диагностики

Стадии конвейера последовательны: MAP → NORMALIZE → ENRICH → MATCH → RESOLVE → PLAN → APPLY. Каждый `TransformResult` может нести диагностику из нескольких предыдущих стадий (upstream), накопленную по цепочке.

**Проблема**: Если стадия ENRICH регистрирует результат, а в нём также есть ошибки от MAP (upstream), они окажутся в отчёте для неправильной стадии.

**Решение** (`_filter_for_report()`):

```python
def _filter_for_report(self, *, errors, warnings):
    if self.include_upstream_diagnostics or self.report_stage is None:
        return errors, warnings, 0, 0
    report_errors = [item for item in errors if _diag_stage_equals(item, self.report_stage)]
    report_warnings = [item for item in warnings if _diag_stage_equals(item, self.report_stage)]
    upstream_errors_count = len(errors) - len(report_errors)
    upstream_warnings_count = len(warnings) - len(report_warnings)
    return report_errors, report_warnings, upstream_errors_count, upstream_warnings_count
```

`upstream_errors_count` и `upstream_warnings_count` попадают в `ReportItem.meta` — их можно видеть в отчёте, но они не входят в `summary.by_stage` текущей стадии.

**`_diag_stage_equals(item, stage)`** — сравнивает item.stage со stage, обрабатывая как enum, так и строковые значения:
```python
def _diag_stage_equals(item: DiagnosticItem, stage: DiagnosticStage) -> bool:
    item_stage = item.stage
    if item_stage == stage:
        return True
    if isinstance(item_stage, str):
        return item_stage.upper() == stage.value
    return False
```

---

### Маскировка секретов в payload

Перед передачей `payload` в `report.add_item()` выполняется двухуровневая маскировка:

**Уровень 1** — `maskSecretsInObject(payload)`:
- Рекурсивно обходит dict/dataclass
- Маскирует поля с именами, соответствующими шаблонам секретов (password, token, secret, и т.д.)

**Уровень 2** — явная маскировка `secret_fields`:
```python
if row_payload is not None and isinstance(row_payload, dict) and secret_fields:
    for field in secret_fields:
        row_payload[field] = "***"
```

`secret_fields` берётся из:
- `result.meta.get("secret_fields")` — список явно помеченных полей из transform DSL
- `result.secret_candidates.keys()` — альтернативный источник (если meta нет)

**Порядок**: сначала `maskSecretsInObject()`, затем явная замена на `"***"`. Таким образом, vault-кандидаты гарантированно замаскированы даже если `maskSecretsInObject()` не распознал имя поля.

---

### Отслеживание vault-кандидатов

`TransformResultProcessor` отслеживает, сколько строк содержат секретные поля-кандидаты для vault:

```python
# В process():
secret_fields: list[str] = []
if result:
    meta_secret_fields = result.meta.get("secret_fields") if result.meta else None
    if isinstance(meta_secret_fields, (list, tuple, set)):
        secret_fields = [str(item) for item in meta_secret_fields if item]
    elif result.secret_candidates:
        secret_fields = list(result.secret_candidates.keys())
    if secret_fields:
        self.vault_candidates_rows += 1
        self.vault_candidates_fields_total += len(secret_fields)
```

**В finalize()** эти счётчики попадают в `context[context_key]`:
```python
{
    "vault_candidates_rows": self.vault_candidates_rows,
    "vault_candidates_fields_total": self.vault_candidates_fields_total,
}
```

---

### finalize() — сброс статистики в context

**Сигнатура**:
```python
def finalize(self) -> CommandResult:
```

**Назначение**: Записать итоговую статистику стадии в `report.context` и вернуть `CommandResult` для CLI.

**Что записывает в context**:
```python
self.report.set_context(
    self.context_key,
    {
        "rows_total": self.rows_total,
        self.ok_label: self.ok_rows,          # например "enriched_rows": 247
        self.failed_label: self.failed_rows,   # например "failed_rows": 3
        "warnings_rows": self.warnings_rows,
        "vault_candidates_rows": self.vault_candidates_rows,
        "vault_candidates_fields_total": self.vault_candidates_fields_total,
    },
)
```

**CommandResult**:
- Если `failed_rows > 0` → `result.add_code(SystemErrorCode.DATA_INVALID)` → status `"error"`
- Иначе → `result.add_code(SystemErrorCode.OK)` → status `"ok"`

---

## 📊 PlanningResultProcessor

**Модуль**: `connector/domain/transform/core/result_processor.py`

Подкласс `TransformResultProcessor`, предназначенный для стадий match/resolve, где на каждую строку приходится planning-специфичная metadata.

### Дополнительные параметры конструктора

```python
PlanningResultProcessor(
    ...всё из TransformResultProcessor...,
    meta_builder: Callable[[TransformResult], dict | None],  # обязателен
    should_skip: Callable[[TransformResult], bool] | None = None,
)
```

- **`meta_builder`**: Вызывается для каждой строки, возвращает dict, который попадает в `ReportItem.meta`. Типичное содержимое: `match_key`, `match_strategy`, `identity_resolution`, `planned_operation`.
- **`should_skip`**: Предикат для пропуска строк (например, неизменённых записей при dry-run). Пропущенные строки не увеличивают `rows_total`.

### Алгоритм process() (override)

```
1. IF result is None → вызвать base process() и вернуть
2. IF should_skip(result) → return (строка пропущена)
3. rows_total += 1
4. resolve errors/warnings, has_errors, status (аналогично base)
5. _filter_for_report() (унаследован)
6. should_store = FAILED OR include_items
7. resolve effective_row_ref (из result.row_ref или result.record)
8. build payload + maskSecretsInObject (аналогично base, без vault-tracking)
9. meta = meta_builder(result) или {}
   meta.setdefault("upstream_errors_count", upstream_errors_count)
   meta.setdefault("upstream_warnings_count", upstream_warnings_count)
10. split_report_diagnostics()
11. report.add_item(status, row_ref, payload, errors, warnings, meta, store)
```

**Ключевое отличие от base**: `meta` заполняется через `meta_builder()`, что позволяет передать planning-контекст (например, `match_key`, `identity`) в `ReportItem.meta` без изменения базового `TransformResultProcessor`.

---

## 📊 EnricherReport

**Модуль**: `connector/domain/transform/enrich/report.py`

Лёгкий per-row аккумулятор статистики операций enrich для одной строки. Создаётся для каждой строки внутри enrich-цикла и сериализуется в `ReportItem.meta["enrich"]`.

### Структура

```python
@dataclass
class EnricherReport:
    operations_total: int = 0             # всего операций enrich для строки
    outcomes: dict[str, int] = ...        # {"APPLIED": 3, "SKIPPED": 1, "FAILED": 0}
    updated_fields: int = 0               # полей обновлено (outcome == "APPLIED")
```

### Методы

**`record(report)`** — учитывает результат одной enrich-операции:
```python
def record(self, report) -> None:
    self.operations_total += 1
    key = report.outcome.value if hasattr(report.outcome, "value") else str(report.outcome)
    self.outcomes[key] = self.outcomes.get(key, 0) + 1
    if report.events:
        self.updated_fields += sum(
            1 for event in report.events
            if getattr(event, "outcome", None) == "APPLIED"
        )
```

**`as_dict()`** — для записи в meta:
```python
{
    "operations_total": 4,
    "outcomes": {"APPLIED": 3, "SKIPPED": 1},
    "updated_fields": 3,
}
```

### Как используется

В enrich-стадии (через `TransformResultProcessor`) `EnricherReport` создаётся per-row, заполняется в цикле операций, а затем `as_dict()` передаётся как `meta["enrich"]` в `report.add_item()`.

---

## 📊 ApplyReportPresenter

**Модуль**: `connector/delivery/presenters/apply_report_presenter.py`

Единственный адаптер, который работает с `ApplyResult` (результат применения плана к target-системе), а не с `TransformResult`. Также единственный компонент, который напрямую устанавливает `collector.status`.

### Сигнатура

```python
class ApplyReportPresenter:
    def present(
        self,
        result: ApplyResult,
        collector: ReportCollector,
        plan: ApplyPlan,
        runtime_context: dict,
    ) -> None:
```

### Алгоритм present()

```
1. Маппинг ApplyResult.summary → collector.add_op():
   - add_op("create", ok=summary.created, failed=summary.create_failed, count=summary.planned_create)
   - add_op("update", ok=summary.updated, failed=summary.update_failed, count=summary.planned_update)
   - add_op("skip",   ok=summary.skipped, failed=0, count=summary.skipped)
   - add_op("apply_failed", ok=0, failed=summary.failed, count=summary.failed)

2. Плановые операции → summary.ops["plan"]:
   - add_op("plan", count=planned_create + planned_update)

3. Установить context["apply"] из runtime_context:
   - collector.set_context("apply", runtime_context.get("apply", {}))

4. Итерировать result.item_outcomes:
   FOR EACH outcome IN result.item_outcomes:
       collector.items.append(ReportItem(
           status=outcome.status,      # "OK" | "FAILED"
           row_ref=outcome.row_ref,
           payload=outcome.payload,
           diagnostics=outcome.diagnostics,
           meta=outcome.meta,
       ))

5. Установить collector.status напрямую:
   IF summary.failed > 0 AND summary.created + summary.updated == 0:
       collector.status = "FAILED"
   ELIF summary.failed > 0:
       collector.status = "PARTIAL"
   ELSE:
       collector.status = "SUCCESS"
```

**Прямая установка `collector.status`**: Это исключение из правила "статус выводится из items". Apply-стадия знает итоговый результат из `ApplyResult.summary` и устанавливает его явно, не полагаясь на `_derive_status()` из хранимых items.

---

## 🔄 Context-блоки: кто и что пишет

Полная таблица всех context-блоков, которые могут присутствовать в `ReportEnvelope.context`:

| Ключ | Модуль-источник | Момент записи | Типичное содержимое |
|------|----------------|--------------|---------------------|
| `"config"` | `report_writer.createEmptyReport()` | До вызова handler | `config_sources: list[str]` — пути к конфиг-файлам |
| `"input"` | обработчик import-команды | В начале обработки | `dataset`, `source_file`, `record_count` |
| `"normalize"` | `TransformResultProcessor.finalize()` (normalize) | После нормализации | `rows_total`, `normalized_rows`, `failed_rows`, `vault_candidates_rows` |
| `"enrich"` | `TransformResultProcessor.finalize()` (enrich) + `commands/enrich.py` | После enrich | `rows_total`, `enriched_rows`, `failed_rows` + vault rollout decision |
| `"match"` | `PlanningResultProcessor.finalize()` (match) | После match | `rows_total`, `matched_rows`, `failed_rows` |
| `"resolve"` | `PlanningResultProcessor.finalize()` (resolve) | После resolve | `rows_total`, `resolved_rows`, `failed_rows` |
| `"apply"` | `ApplyReportPresenter.present()` | После apply | `plan_path`, `dry_run`, `retries`, `target`, `apply_mode` |
| `"cache_refresh"` | `usecases/cache_refresh_service.py` | После cache refresh | `refreshed`, `failed`, `total`, `datasets` |
| `"dictionary"` | `commands/common.attach_dictionary_report_snapshot_if_available()` | Best-effort | `telemetry.snapshot()` из DictionaryProvider |
| `"runtime"` | `report_writer.finalizeReport()` | После handler (в finalize) | `duration_ms`, `log_file`, `cache_dir`, `report_dir` |

### attach_dictionary_report_snapshot_if_available()

**Модуль**: `connector/delivery/commands/common.py`

Специальная best-effort функция для сбора телеметрии dictionary-провайдера без добавления зависимости от dictionary-слоя в отчёт:

```python
def attach_dictionary_report_snapshot_if_available(*, ctx, report) -> None:
    if report is None:
        return
    container = getattr(ctx, "container", None)
    if container is None:
        return
    dictionary_container = getattr(container, "dictionary", None)
    if dictionary_container is None:
        return
    telemetry_provider = getattr(dictionary_container, "telemetry", None)
    if telemetry_provider is None:
        return
    telemetry = telemetry_provider()
    if telemetry is None:
        return
    snapshot = telemetry.snapshot()
    if isinstance(snapshot, dict):
        report.set_context("dictionary", snapshot)
```

**Особенности**:
- Цепочка `getattr(... None)` — защита от отсутствия DI-контейнера или компонента.
- `telemetry_provider()` — вызывает Factory-провайдер DI (не Singleton), создавая свежий экземпляр.
- Блок появляется в отчёте только если dictionary-компонент инициализирован и telemetry доступна.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Transform Core (`result.py`) | Читает из | `TransformResult` | Исходные данные для адаптации |
| ReportCollector (reporting) | Пишет в | `add_item()`, `set_context()`, `add_op()` | Регистрация результатов и контекста |
| Apply Layer (`apply_result.py`) | Читает из | `ApplyResult.summary`, `item_outcomes` | Источник apply-статистики |
| Vault Layer | Читает vault-meta | `result.meta["secret_fields"]`, `result.secret_candidates` | Отслеживание кандидатов и маскировка |
| Dictionary Layer | Best-effort snapshot | `ctx.container.dictionary.telemetry()` | context["dictionary"] |
| sanitize.py | Вызывает | `maskSecretsInObject()` | Маскировка payload |

---

## 🔌 Контракты и границы

### Контракт TransformResultProcessor

**Предусловия**:
- `report` должен быть инициализированным `ReportCollector` (не None).
- `context_key` должен быть уникальным строковым ключом (иначе `set_context()` перезапишет предыдущее значение).

**Постусловия**:
- После каждого `process()`: `rows_total` корректно инкрементирован.
- После `finalize()`: `report.context[context_key]` содержит статистику стадии; возвращён `CommandResult`.

### Контракт ApplyReportPresenter

**Предусловие**: `collector` передан до вызова `present()`; он уже может содержать items от predict/plan-стадий.

**Постусловие**: `collector.status` установлен явно; `summary.ops` содержит create/update/skip/apply_failed; `collector.items` содержит outcomes.

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `TransformResultProcessor` → `ReportCollector` (domain → domain)
- ✅ `TransformResultProcessor` → `DiagnosticItem` (shared domain model)
- ✅ `ApplyReportPresenter` → `ReportCollector` (delivery → domain)
- ✅ `commands/common.py` → `ReportCollector` (delivery → domain, через report.set_context)

**Запрещённые зависимости**:
- ❌ `TransformResultProcessor` → `connector/infra/*` — адаптер домена не знает про инфраструктуру
- ❌ `ReportCollector` → `TransformResult` — обратная зависимость нарушила бы изоляцию
- ❌ Pipeline stages → `ReportEnvelope` — стадии работают только с collector (builder), не с финальным envelope

---

## 💡 Типичные сценарии

### Сценарий 1: Обработка нормализации с фильтрацией upstream ошибок

```python
processor = TransformResultProcessor(
    report=report,
    include_items=False,
    context_key="normalize",
    ok_label="normalized_rows",
    failed_label="failed_rows",
    report_stage=DiagnosticStage.NORMALIZE,     # фильтровать только NORMALIZE-диагностику
    include_upstream_diagnostics=False,
)

for result in normalize_results:
    processor.process(result)
    # result.errors может содержать MAP-ошибки (upstream)
    # _filter_for_report() оставит только те, у которых stage == NORMALIZE
    # MAP-ошибки попадут в meta["upstream_errors_count"]

cmd_result = processor.finalize()
# report.context["normalize"] = {rows_total, normalized_rows, failed_rows, ...}
```

---

### Сценарий 2: Planning-стадия с meta_builder

```python
def build_match_meta(result: TransformResult) -> dict:
    return {
        "match_key": result.match_key.value if result.match_key else None,
        "match_strategy": result.meta.get("match_strategy"),
        "identity": result.meta.get("identity_primary"),
    }

processor = PlanningResultProcessor(
    report=report,
    include_items=include_items,
    context_key="match",
    ok_label="matched_rows",
    failed_label="unmatched_rows",
    meta_builder=build_match_meta,
    report_stage=DiagnosticStage.MATCH,
)

for result in match_results:
    processor.process(result)
    # ReportItem.meta["match_key"] = "employee_id_12345"
    # ReportItem.meta["match_strategy"] = "exact"
```

---

### Сценарий 3: ApplyReportPresenter с частичными сбоями

```python
presenter = ApplyReportPresenter()
presenter.present(
    result=apply_result,       # ApplyResult(summary=..., item_outcomes=[...])
    collector=report,
    plan=plan,
    runtime_context={
        "apply": {
            "dry_run": False,
            "target": "ankey_rest",
            "plan_path": "plans/run-xyz.json",
        }
    },
)
# После present():
# report.summary.ops == {
#   "create": {"ok": 10, "failed": 0, "count": 10},
#   "update": {"ok": 5,  "failed": 2, "count": 7},
#   "apply_failed": {"ok": 0, "failed": 2, "count": 2},
# }
# report.status == "PARTIAL" (есть ошибки, но есть и успешные)
# report.context["apply"] == {"dry_run": False, "target": "ankey_rest", ...}
```

---

### Сценарий 4: Маскировка vault-кандидата в payload

```python
# TransformResult с секретным полем "password"
result.meta = {"secret_fields": ["password"]}
result.row = {"employee_id": "E001", "name": "Alice", "password": "s3cr3t!"}

# В process():
# 1. maskSecretsInObject(row) → маскирует известные паттерны
# 2. payload["password"] = "***"  # явная маскировка по secret_fields

# В ReportItem:
# payload == {"employee_id": "E001", "name": "Alice", "password": "***"}
# meta["secret_candidate_fields"] == ["password"]
```

---

## 📌 Важные детали

### Особенности реализации

- **`process()` не может вернуть ошибку**: все исключения должны быть обработаны вызывающим кодом до передачи в processor; processor предполагает корректные входные данные.
- **`include_items=True` → все строки хранятся**: Используется для команд, где пользователю важна полная детализация (например, dry-run apply). По умолчанию `include_items=False` — хранятся только FAILED.
- **`force_failed=True`**: Принудительно помечает строку как FAILED, даже если ошибок нет; используется, когда upstream-стадия вернула None (строка не может быть обработана).
- **`errors_override` / `warnings_override`**: Позволяют передать конкретный набор диагностик вместо тех, что в `result.errors` — используется при инжекции синтетических ошибок (например, при timeout).
- **`PlanningResultProcessor.should_skip()`**: Скипнутые строки не фиксируются в отчёте вообще (ни счётчики, ни items) — это отличает skip от FAILED.

### 🚨 Failure Modes

| Ситуация | Поведение | Как обработать |
|----------|-----------|---------------|
| `result=None` + `force_failed=False` | `rows_total += 1`, `status="OK"`, пустой payload | Передавать `force_failed=True` для явного FAILED при отсутствии result |
| `payload_builder` бросает исключение | Не перехватывается — исключение всплывает выше | Реализовывать `payload_builder` без исключений; использовать try/except снаружи |
| `report_stage` не соответствует ни одной диагностике | Все диагностики идут в upstream_count; report_errors=[] | Нормальное поведение при отсутствии ошибок текущей стадии |
| `maskSecretsInObject` не распознаёт имя поля | Поле не маскируется функцией, но `secret_fields` маскировка ("***") всё равно применяется | Убедиться, что vault-поля всегда передаются в `result.meta["secret_fields"]` |
| `finalize()` вызван без `process()` | `rows_total=0`, all counters zero, `CommandResult.status="ok"` | Нормально для пустого датасета |

### ⚠️ Инварианты системы

1. **Инвариант: Payload без секретов**
   - **Что**: `ReportItem.payload` никогда не содержит незамаскированных секретных значений.
   - **Почему важно**: Отчёт хранится на диске и может быть передан во внешние системы.
   - **Где проверяется**: `TransformResultProcessor.process()`, двухуровневая маскировка (maskSecretsInObject + explicit "***").

2. **Инвариант: stage-атрибуция ошибок**
   - **Что**: Диагностика в `ReportItem.diagnostics` принадлежит именно стадии, чей `TransformResultProcessor` её зафиксировал.
   - **Почему важно**: `by_stage` в summary корректно показывает, где возникли ошибки.
   - **Где проверяется**: `_filter_for_report()` фильтрует по `report_stage`.

3. **Инвариант: finalize() вызывается ровно один раз на стадию**
   - **Что**: `set_context(context_key, ...)` вызывается один раз; второй вызов перезапишет статистику.
   - **Почему важно**: Дублирование `finalize()` испортит `context[context_key]`.
   - **Где проверяется**: По архитектуре — processor создаётся per-stage, finalize() вызывается по завершении.

### ⏱️ Performance заметки

**Узкие места**:
- `maskSecretsInObject()` — рекурсивный обход dict; при payload из 100+ полей выполняется за ~1 мс. Не является bottleneck для типичных датасетов (< 10K строк).
- `_filter_for_report()` — линейная фильтрация `O(n)` по числу диагностик; обычно < 10 на строку → незначительно.
- `split_report_diagnostics()` — аналогично, два прохода по небольшому списку.

**Оптимизации**:
- `should_store` проверяется до построения payload: если `False` → никакой обработки payload нет.
- `secret_fields` маскировка выполняется только если `should_store=True` (payload строится только для хранимых items).

---

## 🛠️ Как расширять

### Добавить новую стадию конвейера с отчётностью

1. Создать `TransformResultProcessor` с `context_key="my_stage"`:
   ```python
   processor = TransformResultProcessor(
       report=report,
       include_items=False,
       context_key="my_stage",
       ok_label="processed_rows",
       failed_label="failed_rows",
       report_stage=DiagnosticStage.MY_STAGE,
   )
   ```

2. В цикле по строкам вызывать `processor.process(result)`.

3. По завершении вызвать `processor.finalize()` → `CommandResult`.

4. В `context["my_stage"]` автоматически появится статистика.

### Добавить новый context-блок от команды

```python
# В обработчике команды:
report.set_context("my_command_context", {
    "param1": args.param1,
    "param2": args.param2,
})
```

### Добавить planning-specific meta

Реализовать `meta_builder` для `PlanningResultProcessor`:
```python
def build_my_meta(result: TransformResult) -> dict:
    return {
        "custom_field": result.meta.get("custom"),
        "match_score": result.meta.get("score", 0),
    }
```

---

## ❓ FAQ

### Когда использовать `include_upstream_diagnostics=True`?

Когда стадии конвейера жёстко связаны и ошибка upstream стадии фактически является ошибкой текущей. Например, если enrich-стадия перезапускает всю обработку строки (re-enrich) и ошибка из MAP должна быть видна в enrich-контексте. По умолчанию `False` — строгая stage-атрибуция.

**Правило**: Используйте `False` (дефолт) для стандартных линейных стадий. Используйте `True` только если стадия намеренно агрегирует диагностику предыдущих шагов.

---

### Почему `PlanningResultProcessor` не наследует явно `finalize()`?

`finalize()` унаследован из `TransformResultProcessor` без изменений — он записывает те же счётчики (rows_total, ok_rows, failed_rows, etc.) в `context[context_key]`. Planning-специфичная логика инкапсулирована в `process()` и `meta_builder`. Добавление `finalize()` в подкласс потребовалось бы только если нужны дополнительные счётчики (например, `skipped_rows`).

---

### Что происходит с `EnricherReport`, если enrich операция упала?

`EnricherReport.record(report)` вызывается только для завершённых операций enrich. Если операция бросила исключение, вызывающий код (enrich_core.py) обрабатывает его и создаёт `DiagnosticItem` с severity=ERROR. Затем этот `DiagnosticItem` передаётся в `TransformResultProcessor.process()` через `errors_override`, и строка помечается FAILED. `EnricherReport` при этом может не иметь записи для упавшей операции.

---

### Почему `ApplyReportPresenter` устанавливает `collector.status` напрямую?

Apply — финальная стадия конвейера, которая знает общий итог из `ApplyResult.summary` (created + updated + failed). `_derive_status()` работает только из хранимых `ReportItem`-объектов, которые для apply-стадии добавляются через `collector.items.append()` без `store`-логики `add_item()`. Это позволяет ApplyReportPresenter иметь полный контроль над статусом, основанным на бизнес-результате apply-операций.

---

### Как `upstream_errors_count` отличается от `errors_total` в summary?

- `summary.errors_total` — суммарное количество `ReportDiagnostic`-объектов в хранимых items (из `_count_diagnostics()`).
- `meta.upstream_errors_count` в `ReportItem` — количество ошибок данной строки из предыдущих стадий (upstream), которые были отфильтрованы `_filter_for_report()` и не вошли в `item.diagnostics`.

`upstream_errors_count` позволяет аналитику увидеть "скрытые" ошибки строки, не попавшие в диагностику из-за stage-фильтрации.

---

### Можно ли использовать `PlanningResultProcessor` для стадии apply?

Нет — apply использует `ApplyReportPresenter`, который работает с `ApplyResult` (а не `TransformResult`). `PlanningResultProcessor` предназначен исключительно для стадий match/resolve, которые возвращают `TransformResult`.

---

## 🧪 Тестирование

### Unit-тесты TransformResultProcessor

```python
def test_process_failed_row_stores_item():
    report = ReportCollector(run_id="test", command="import", started_at=datetime.now())
    processor = TransformResultProcessor(
        report=report,
        include_items=False,         # OK строки не хранятся
        context_key="normalize",
        ok_label="normalized_rows",
        failed_label="failed_rows",
    )

    # FAILED строка — должна храниться
    result = make_transform_result(errors=[make_diag("field_missing")])
    processor.process(result)

    assert processor.rows_total == 1
    assert processor.failed_rows == 1
    assert processor.ok_rows == 0


def test_process_ok_row_not_stored_when_include_items_false():
    report = ReportCollector(run_id="test", command="import", started_at=datetime.now())
    processor = TransformResultProcessor(
        report=report,
        include_items=False,
        context_key="test",
        ok_label="ok",
        failed_label="fail",
    )

    result = make_transform_result(errors=[])   # OK строка
    processor.process(result)

    report.finish()
    envelope = report.build()
    assert len(envelope.items) == 0       # не хранится
    assert envelope.summary.rows_passed == 1  # счётчик полный


def test_stage_filter_upstream_diagnostics():
    report = ReportCollector(run_id="test", command="import", started_at=datetime.now())
    processor = TransformResultProcessor(
        report=report,
        include_items=True,
        context_key="enrich",
        ok_label="ok",
        failed_label="fail",
        report_stage=DiagnosticStage.ENRICH,
        include_upstream_diagnostics=False,
    )

    # Ошибка из MAP (upstream), ошибка из ENRICH (текущая)
    map_error = make_diag("map_error", stage=DiagnosticStage.MAP)
    enrich_error = make_diag("enrich_error", stage=DiagnosticStage.ENRICH)
    result = make_transform_result(errors=[map_error, enrich_error])
    processor.process(result, force_failed=True)

    report.finish()
    envelope = report.build()
    item = envelope.items[0]
    # Только ENRICH-диагностика в item.diagnostics
    assert len(item.diagnostics) == 1
    assert item.diagnostics[0].code == "enrich_error"
    # MAP-ошибка в meta
    assert item.meta["upstream_errors_count"] == 1


def test_secret_field_masked_in_payload():
    report = ReportCollector(run_id="test", command="import", started_at=datetime.now())
    processor = TransformResultProcessor(
        report=report,
        include_items=True,
        context_key="test",
        ok_label="ok",
        failed_label="fail",
    )

    result = make_transform_result(
        row={"employee_id": "E001", "password": "s3cr3t"},
        meta={"secret_fields": ["password"]},
    )
    processor.process(result)

    report.finish()
    envelope = report.build()
    assert envelope.items[0].payload["password"] == "***"
    assert envelope.items[0].payload["employee_id"] == "E001"
```

### Unit-тесты DiagnosticItem → ReportDiagnostic

```python
def test_to_report_diagnostics_maps_fields():
    error = DiagnosticItem(
        severity=DiagnosticSeverity.ERROR,
        stage="ENRICH",
        code="test_code",
        field="test_field",
        message="test message",
    )
    result = to_report_diagnostics([error], None)

    assert len(result) == 1
    assert result[0].severity == "error"
    assert result[0].stage == "ENRICH"
    assert result[0].code == "test_code"


def test_split_report_diagnostics_separates():
    error = DiagnosticItem(severity=DiagnosticSeverity.ERROR, stage="MATCH", code="err")
    warning = DiagnosticItem(severity=DiagnosticSeverity.WARNING, stage="MATCH", code="warn")

    errors, warnings = split_report_diagnostics([error], [warning])
    assert len(errors) == 1 and errors[0].severity == "error"
    assert len(warnings) == 1 and warnings[0].severity == "warning"


def test_report_diagnostic_passthrough():
    # Уже-ReportDiagnostic не конвертируется
    diag = ReportDiagnostic(severity="warning", stage="ENRICH", code="x", field=None, message=None)
    result = to_report_diagnostics(None, [diag])
    assert result[0] is diag   # тот же объект
```

---

## 🔗 Связанные документы

- [report-models.md](./report-models.md) — ReportCollector, ReportEnvelope, все domain models
- [report-delivery.md](./report-delivery.md) — CLI lifecycle, run_with_report(), JSON I/O
- [vault-core.md](../vault/vault-core.md) — secret_candidates, secret_fields в transform pipeline
- [dictionary-delivery.md](../dictionary/dictionary-delivery.md) — dictionary telemetry snapshot

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ | xORex-LC |
