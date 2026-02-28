# Report Models — Domain Models and ReportCollector

> **Structured execution telemetry**: every pipeline command builds a `ReportCollector` that accumulates per-row results, stage counters, and context blocks, then serializes to a `ReportEnvelope` JSON artifact.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
  - [ReportEnvelope — корневой объект](#reportenvelope--корневой-объект)
  - [ReportMeta — метаданные запуска](#reportmeta--метаданные-запуска)
  - [ReportSummary — агрегированная статистика](#reportsummary--агрегированная-статистика)
  - [ReportDiagnostic — атомарная диагностика](#reportdiagnostic--атомарная-диагностика)
  - [ReportItem — результат по одной записи](#reportitem--результат-по-одной-записи)
  - [RowRef — ссылка на исходную строку](#rowref--ссылка-на-исходную-строку)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
  - [ReportCollector.add_item()](#reportcollectoradd_item)
  - [ReportCollector._derive_status()](#reportcollector_derive_status)
  - [ReportCollector.build()](#reportcollectorbuild)
  - [asdict_report()](#asdict_report)
- [🔄 Context-пространство имён](#-context-пространство-имён)
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

**Назначение**: Предоставить единый механизм сбора структурированной телеметрии выполнения для каждой CLI-команды ETL-конвейера — результаты по строкам, счётчики по стадиям, контекстные блоки — с итоговой сериализацией в JSON-артефакт.

**Ключевая ответственность**:
- Определить все доменные типы данных отчёта: `ReportEnvelope`, `ReportMeta`, `ReportSummary`, `ReportDiagnostic`, `ReportItem`.
- Реализовать `ReportCollector` — изменяемый построитель (builder), который накапливает состояние по мере выполнения конвейера.
- Вывести итоговый статус (`SUCCESS` / `PARTIAL` / `FAILED`) из агрегированных данных по записям.
- Ограничить список хранимых items капом `items_limit` при полном накоплении summary-счётчиков.
- Произвести сериализацию `ReportEnvelope` в плоский словарь (`asdict_report()`) для JSON-вывода.

**Расположение в кодовой базе**:
- `connector/domain/reporting/collector.py` — `ReportCollector`, `asdict_report()`
- `connector/domain/reporting/models.py` — все dataclass-модели
- `connector/domain/models.py` — `RowRef`, `DiagnosticItem`, `DiagnosticStage`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/
├── domain/
│   ├── reporting/
│   │   ├── collector.py       # ReportCollector (builder) + asdict_report()
│   │   ├── models.py          # ReportEnvelope, ReportMeta, ReportSummary,
│   │   │                      #   ReportDiagnostic, ReportItem
│   │   └── diagnostics.py     # DiagnosticItem → ReportDiagnostic conversion
│   └── models.py              # RowRef, DiagnosticItem, DiagnosticStage (shared domain)
├── infra/
│   └── artifacts/
│       └── report_writer.py   # createEmptyReport(), finalizeReport(), writeReportJson()
└── delivery/
    └── cli/
        └── runtime.py         # run_with_report() — lifecycle wrapper
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Class Diagram](../../../uml/pipeline/report_layer/report_layer_class.puml) | Структура классов и связи |
| Sequence | [Sequence Diagram](../../../uml/pipeline/report_layer/report_layer_sequence.puml) | Взаимодействие компонентов |
| Activity | [Activity Diagram](../../../uml/pipeline/report_layer/report_layer_activity.puml) | Алгоритм выполнения |
| Components | [Component Diagram](../../../uml/pipeline/report_layer/report_layer_components.puml) | Компонентная структура |

**PlantUML исходники**: `docs/uml/pipeline/report_layer/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Builder (Построитель)

**Где применяется**: `ReportCollector` — изменяемый построитель с методами-мутаторами; итоговый `ReportEnvelope` создаётся одним вызовом `build()` и после него не изменяется.

**Реализация в коде**:
- **Builder**: `ReportCollector` в `connector/domain/reporting/collector.py`
- **Product**: `ReportEnvelope` в `connector/domain/reporting/models.py`

**Пример использования**:
```python
report = ReportCollector(run_id="abc-123", command="import", started_at=datetime.now())
report.set_meta(dataset="employees", app_version="1.2.0", git_rev="abc1234")
report.set_context("config", {"config_sources": ["/etc/ankey/app.yaml"]})
report.add_item(status="FAILED", row_ref=ref, payload=row, errors=[diag])
report.finish()
envelope = report.build()  # → ReportEnvelope (неизменяемый снимок)
```

**Зачем**: Позволяет передавать `ReportCollector` по ссылке через все стадии конвейера без передачи итогового объекта, избегая преждевременной финализации.

---

#### Паттерн 2: Immutable Value Object

**Где применяется**: `ReportDiagnostic` — `@dataclass(frozen=True)`, не допускает мутации после создания. Аналогично `ReportEnvelope` создаётся за один шаг и не изменяется.

**Реализация в коде**:
- `ReportDiagnostic` в `connector/domain/reporting/models.py` — `frozen=True`

**Зачем**: Диагностика атомарна; нельзя изменить severity или stage после того, как диагностика создана — это предотвращает случайные мутации при агрегации.

---

#### Паттерн 3: Thread-local Accumulator

**Где применяется**: `ReportCollector` создаётся один раз per-invocation и передаётся явным параметром через все обработчики. Счётчики накапливаются in-place без глобального состояния.

**Зачем**: Нет shared state между параллельными запусками; каждый `run_with_report()` имеет свой изолированный `ReportCollector`.

### Диаграмма зависимостей

```
CLI runtime (run_with_report)
  └──creates──► ReportCollector
                  │
                  ├──mutated by──► TransformResultProcessor    (domain/transform)
                  ├──mutated by──► ApplyReportPresenter        (delivery/presenters)
                  ├──mutated by──► command handlers             (delivery/commands)
                  └──finalized by──► report_writer.finalizeReport()
                                          │
                                          └──serialized by──► asdict_report()
                                                                    │
                                                                    └──► ReportEnvelope (JSON)
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `ReportCollector` | Изменяемый builder отчёта | `set_meta()`, `set_context()`, `add_op()`, `add_item()`, `finish()`, `build()` |
| `ReportEnvelope` | Итоговый неизменяемый снимок | dataclass, читается через поля |
| `ReportMeta` | Метаданные запуска | dataclass: run_id, command, started_at, finished_at, duration_ms |
| `ReportSummary` | Агрегированные счётчики | dataclass: rows_total, errors_total, by_stage, ops |
| `ReportDiagnostic` | Атомарная диагностическая запись | frozen dataclass: severity, stage, code, field, message |
| `ReportItem` | Результат обработки одной строки | dataclass: status, row_ref, payload, diagnostics, meta |

### Ключевые функции

| Функция | Назначение |
|---------|-----------|
| `asdict_report(envelope)` | Глубокая сериализация `ReportEnvelope` → `dict` для JSON |
| `_derive_status(items)` | Вывод итогового статуса из списка items |
| `_should_store_item(store)` | Применение `items_limit` к хранению items |
| `_count_diagnostics(items)` | Подсчёт `errors_total`, `warnings_total`, `by_stage` из items |

---

## 🗂️ Модели данных

### ReportEnvelope — корневой объект

**Назначение**: Финальный сериализуемый снимок всего отчёта. Создаётся вызовом `ReportCollector.build()` и больше не изменяется.

**Структура**:
```python
@dataclass
class ReportEnvelope:
    status: str                        # "SUCCESS" | "PARTIAL" | "FAILED"
    meta: ReportMeta                   # метаданные запуска
    summary: ReportSummary             # агрегированные счётчики
    items: list[ReportItem]            # детализация по строкам (обрезается items_limit)
    context: dict[str, dict]           # именованные контекстные блоки от стадий
```

**JSON-схема верхнего уровня**:
```json
{
  "status": "PARTIAL",
  "meta": { ... },
  "summary": { ... },
  "items": [ ... ],
  "context": {
    "config": { ... },
    "runtime": { ... },
    "apply": { ... }
  }
}
```

**Lifecycle**:
1. **Создание**: `ReportCollector.build()` после вызова `finish()`.
2. **Использование**: `asdict_report(envelope)` → `json.dump(...)` в report_writer.
3. **Неизменность**: После `build()` объект не мутируется; все дальнейшие вызовы `build()` возвращают тот же снимок.

---

### ReportMeta — метаданные запуска

**Назначение**: Идентификатор и временны́е параметры конкретного запуска команды.

**Структура**:
```python
@dataclass
class ReportMeta:
    run_id: str                        # UUID запуска (из args или generated)
    dataset: str | None                # имя датасета (если применимо)
    command: str                       # имя CLI-команды ("import", "apply", etc.)
    started_at: str                    # ISO 8601 timestamp начала
    finished_at: str | None            # ISO 8601 timestamp конца (после finish())
    duration_ms: int | None            # длительность в миллисекундах
    items_limit: int                   # максимум items в envelope.items
    items_truncated: bool              # True если items_limit превышен
    app_version: str | None            # версия приложения
    git_rev: str | None                # git-ревизия
```

**Заполнение**:
- `run_id`, `command`, `started_at`, `items_limit` — из конструктора `ReportCollector.__init__()`.
- `dataset`, `app_version`, `git_rev` — через `report.set_meta(dataset=..., app_version=..., git_rev=...)`.
- `finished_at`, `duration_ms` — через `report.finish()` (вызывается в `finalizeReport()`).
- `items_truncated` — устанавливается в `_should_store_item()` при превышении лимита.

---

### ReportSummary — агрегированная статистика

**Назначение**: Сводные счётчики по всем обработанным строкам и операциям. Счётчики полные — не обрезаются `items_limit`.

**Структура**:
```python
@dataclass
class ReportSummary:
    rows_total: int = 0                # всего строк обработано
    rows_passed: int = 0               # строк с status="OK"
    rows_blocked: int = 0              # строк с status="FAILED"
    rows_with_warnings: int = 0        # строк с ненулевыми warnings
    errors_total: int = 0              # суммарно ошибок (из items)
    warnings_total: int = 0            # суммарно предупреждений (из items)
    by_stage: dict[str, int]           # ошибок по стадиям {"ENRICH": 3, "MATCH": 1}
    ops: dict[str, dict[str, int]]     # операции apply {"create": {"ok": 5, "failed": 1}}
```

**`by_stage`**: Ключи — строковые имена стадий из `DiagnosticStage` enum (например, `"ENRICH"`, `"MATCH"`, `"RESOLVE"`, `"APPLY"`). Заполняется в `_count_diagnostics()` из `ReportDiagnostic.stage` хранимых items.

**`ops`**: Заполняется через `report.add_op(name, ok, failed, count)`. Типичные ключи:
- `"create"` — создание записей в target
- `"update"` — обновление записей в target
- `"skip"` — пропуск без изменений
- `"apply_failed"` — сбой операции apply
- `"plan"` — плановые операции (planned_create, planned_update)

**Инварианты счётчиков**:
- `rows_total == rows_passed + rows_blocked` — строки всегда попадают в один из двух статусов.
- `rows_total >= rows_with_warnings` — строка с предупреждениями может быть OK или FAILED.
- `errors_total` и `warnings_total` считаются только из хранимых items → могут быть занижены при `items_truncated=True`.

---

### ReportDiagnostic — атомарная диагностика

**Назначение**: Неизменяемая запись об одной проблеме (ошибке или предупреждении), привязанной к стадии конвейера и конкретному полю.

**Структура**:
```python
@dataclass(frozen=True)
class ReportDiagnostic:
    severity: str                      # "error" | "warning"
    stage: str | None                  # имя стадии ("ENRICH", "MATCH", etc.)
    code: str | None                   # машиночитаемый код ("field_missing", etc.)
    field: str | None                  # имя поля, к которому относится диагностика
    message: str | None                # человекочитаемое описание
    rule: str | None                   # имя правила (если есть)
    details: dict | None               # произвольные дополнительные данные
```

**Источники создания**:
1. Из `DiagnosticItem` через `to_report_diagnostics()` / `_from_item()` в `connector/domain/reporting/diagnostics.py`.
2. Напрямую в `ApplyReportPresenter` при маппинге item_outcomes.

**Frozen-семантика**: После создания поля не меняются. Это гарантирует, что диагностика, добавленная в `ReportItem.diagnostics`, не будет случайно изменена после вызова `add_item()`.

**Пример**:
```python
ReportDiagnostic(
    severity="error",
    stage="ENRICH",
    code="secret_store_failed",
    field="password",
    message="Failed to store secret for field 'password'",
    rule=None,
    details={"reason": "vault_not_ready"},
)
```

---

### ReportItem — результат по одной записи

**Назначение**: Полная информация о результате обработки одной строки источника — статус, ссылка на строку, payload, диагностики, метаданные стадии.

**Структура**:
```python
@dataclass
class ReportItem:
    status: str                          # "OK" | "FAILED"
    row_ref: RowRef | None               # ссылка на исходную строку
    payload: dict | None                 # обработанный payload (с маскировкой секретов)
    diagnostics: list[ReportDiagnostic]  # список ошибок и предупреждений
    meta: dict | None                    # stage-специфичные метаданные
```

**`meta` — типичные ключи**:
- `"match_key"` — ключ сопоставления (из `PlanningResultProcessor`)
- `"secret_candidate_fields"` — список полей-кандидатов для vault (из `TransformResultProcessor`)
- `"upstream_errors_count"` — количество ошибок из предыдущих стадий, не вошедших в диагностику из-за фильтрации по `report_stage`
- `"upstream_warnings_count"` — аналогично для предупреждений
- `"enrich"` — `EnricherReport.as_dict()` для стадии enrich

**Хранение vs. счёт**: `ReportItem` добавляется в `envelope.items` только если `store=True` (передаётся из `TransformResultProcessor`). Но счётчики `rows_total`, `rows_passed`, `rows_blocked`, `rows_with_warnings` инкрементируются независимо от `store`.

---

### RowRef — ссылка на исходную строку

**Назначение**: Минимальный идентификатор строки источника для навигации в отчёте.

**Структура** (`connector/domain/models.py`):
```python
@dataclass
class RowRef:
    line_no: int | None             # номер строки в исходном файле
    row_id: str | None              # внутренний идентификатор записи
    identity_primary: str | None    # имя primary-идентификатора (например, "employee_id")
    identity_value: str | None      # значение primary-идентификатора
```

**Как создаётся** (в `TransformResultProcessor.process()`):
```python
# Приоритет 1: явный row_ref из аргумента
effective_row_ref = row_ref or (result.row_ref if result else None)

# Приоритет 2: из result.record
if effective_row_ref is None and result is not None:
    effective_row_ref = RowRef(
        line_no=result.record.line_no,
        row_id=result.record.record_id,
        identity_primary=None,
        identity_value=None,
    )
```

---

## 📊 Ключевые методы и алгоритмы

### ReportCollector.add_item()

**Расположение**: `connector/domain/reporting/collector.py`

**Сигнатура**:
```python
def add_item(
    self,
    *,
    status: str,
    row_ref: RowRef | None,
    payload: dict | None,
    errors: list[ReportDiagnostic],
    warnings: list[ReportDiagnostic],
    meta: dict | None,
    store: bool,
) -> None:
```

**Назначение**: Зарегистрировать результат обработки одной строки: обновить счётчики summary, и при `store=True` — сохранить `ReportItem` в список items (с учётом лимита).

**Алгоритм**:
```
1. Обновить summary-счётчики:
   - rows_total += 1
   - IF status == "OK": rows_passed += 1
   - ELSE: rows_blocked += 1
   - IF warnings: rows_with_warnings += 1

2. IF store == True:
   - _should_store_item() → проверить items_limit
     - IF len(items) < items_limit:
         создать ReportItem(status, row_ref, payload, diagnostics, meta)
         items.append(item)
     - ELSE:
         items_truncated = True  (флаг, дальше items не пополняются)

3. summary-счётчики (rows_total и т.д.) всегда полные
   (не зависят от store или items_limit)
```

**Инвариант**: Счётчики `rows_total`, `rows_passed`, `rows_blocked`, `rows_with_warnings` всегда корректны, даже если `envelope.items` обрезан.

---

### ReportCollector._derive_status()

**Расположение**: `connector/domain/reporting/collector.py`

**Назначение**: Вычислить итоговый статус отчёта из хранимых items.

**Алгоритм** (таблица решений):

```
Условие                                          → Статус
─────────────────────────────────────────────────────────
items пуст                                       → "SUCCESS"
все items имеют status == "FAILED"               → "FAILED"
все items имеют status == "OK"                   → "SUCCESS"
есть и "OK" и "FAILED" items                     → "PARTIAL"
```

**Важно**: Статус выводится только из хранимых items (не из summary-счётчиков). Если `items_truncated=True`, статус отражает только первые `items_limit` записей. Исключение — `ApplyReportPresenter`, который может напрямую установить `collector.status` после apply.

---

### ReportCollector.build()

**Расположение**: `connector/domain/reporting/collector.py`

**Сигнатура**:
```python
def build(self) -> ReportEnvelope:
```

**Назначение**: Зафиксировать текущее состояние ReportCollector в неизменяемый `ReportEnvelope`.

**Алгоритм**:
```
1. _count_diagnostics(items):
   - Итерировать по хранимым items
   - Суммировать errors_total, warnings_total
   - Построить by_stage: dict[str, int] по ReportDiagnostic.stage

2. Обновить summary:
   - summary.errors_total = errors_total
   - summary.warnings_total = warnings_total
   - summary.by_stage = by_stage

3. _derive_status() → status

4. Заполнить meta (финальные поля уже установлены через finish()):
   - meta.items_limit = self._items_limit
   - meta.items_truncated = self._items_truncated

5. Вернуть ReportEnvelope(
       status=status,
       meta=meta,
       summary=summary,
       items=list(self._items),
       context=dict(self._context),
   )
```

**Идемпотентность**: Повторный вызов `build()` после `finish()` возвращает новый объект с тем же содержимым (без side effects).

---

### asdict_report()

**Расположение**: `connector/domain/reporting/collector.py`

**Сигнатура**:
```python
def asdict_report(envelope: ReportEnvelope) -> dict:
```

**Назначение**: Глубокая сериализация `ReportEnvelope` в плоский Python-словарь, пригодный для `json.dump()`.

**Что делает**:
- Конвертирует все вложенные dataclass-поля рекурсивно.
- Преобразует `datetime` → ISO 8601 строки.
- Преобразует `None`-поля → JSON `null`.
- Не применяет camelCase — все ключи в snake_case (так же, как поля dataclass'ов).

**Пример выходного словаря**:
```python
{
    "status": "PARTIAL",
    "meta": {
        "run_id": "abc-123",
        "dataset": "employees",
        "command": "import",
        "started_at": "2026-02-27T10:00:00Z",
        "finished_at": "2026-02-27T10:00:05Z",
        "duration_ms": 5123,
        "items_limit": 1000,
        "items_truncated": False,
        "app_version": "1.2.0",
        "git_rev": "abc1234"
    },
    "summary": {
        "rows_total": 250,
        "rows_passed": 247,
        "rows_blocked": 3,
        "rows_with_warnings": 12,
        "errors_total": 3,
        "warnings_total": 15,
        "by_stage": {"ENRICH": 2, "MATCH": 1},
        "ops": {
            "create": {"ok": 200, "failed": 0, "count": 200},
            "update": {"ok": 47, "failed": 3, "count": 50}
        }
    },
    "items": [ ... ],
    "context": {
        "config": {"config_sources": ["/etc/ankey/app.yaml"]},
        "runtime": {"duration_ms": 5123, "log_file": "logs/run-abc-123.log"},
        "apply": {"dry_run": False, "target": "ankey_rest"}
    }
}
```

---

## 🔄 Context-пространство имён

`ReportCollector._context` — это `dict[str, dict]`, куда разные части конвейера записывают именованные блоки через `report.set_context(name, value)`. Ни один из блоков не является обязательным — каждый присутствует только если соответствующая стадия выполнялась.

| Ключ | Кто устанавливает | Содержимое |
|------|-----------------|-----------|
| `"config"` | `report_writer.createEmptyReport()` | `config_sources` — список путей к конфиг-файлам |
| `"input"` | обработчик команды import | dataset, source_file, record_count |
| `"enrich"` | `connector/delivery/commands/enrich.py` | vault_rollout decision (mode, reason, triggered) |
| `"normalize"` | обработчик normalize | статистика нормализации |
| `"apply"` | `connector/delivery/commands/import_apply.py` | plan_path, dry_run, retries, target |
| `"cache_refresh"` | `usecases/cache_refresh_service.py` | статистика обновления кэша |
| `"dictionary"` | `commands/common.attach_dictionary_report_snapshot_if_available()` | telemetry snapshot из DictionaryProvider (best-effort) |
| `"runtime"` | `report_writer.finalizeReport()` | duration_ms, log_file, cache_dir, report_dir |

**Семантика `set_context()`**: Последняя запись с тем же ключом перезаписывает предыдущую — коллизии ключей не накапливаются.

**Пример context в JSON**:
```json
{
  "config": {
    "config_sources": ["/etc/ankey/app.yaml", "/home/user/.ankey.yaml"]
  },
  "enrich": {
    "vault_rollout": {
      "mode": "canary",
      "triggered": true,
      "reason": "canary_bucket_in_range"
    }
  },
  "runtime": {
    "duration_ms": 5123,
    "log_file": "logs/run-abc-123.log",
    "cache_dir": "cache/",
    "report_dir": "reports/"
  }
}
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Transform (result_processor) | Мутирует ReportCollector | `report.add_item()`, `report.set_context()` | Регистрация per-row результатов по стадиям transform |
| Apply (ApplyReportPresenter) | Мутирует ReportCollector | `report.add_op()`, `collector.items.append()` | Маппинг ApplyResult → report stats |
| report_writer (infra) | Создаёт и финализирует | `createEmptyReport()`, `finalizeReport()`, `writeReportJson()` | Lifecycle I/O |
| CLI runtime | Оркестрирует lifecycle | `run_with_report()` | Создание, передача через handler, финализация |
| Commands (delivery) | Устанавливают контекст | `report.set_context()` | Заполнение именованных context-блоков |

---

## 🔌 Контракты и границы

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `ReportCollector` → `models.py` — только собственные dataclass-типы
- ✅ `ReportCollector` → `connector/domain/models.py` — `RowRef`, `DiagnosticStage` (shared domain)
- ✅ `report_writer` → `ReportCollector` — инфраструктурный код создаёт и финализирует
- ✅ `TransformResultProcessor` → `ReportCollector` — домен мутирует builder

**Запрещённые зависимости**:
- ❌ `ReportCollector` → `connector/infra/*` — collector не знает про I/O
- ❌ `ReportCollector` → `connector/delivery/*` — нет обратной зависимости на CLI
- ❌ Pipeline stages → `ReportEnvelope` напрямую — stages работают только с collector, не с финальным envelope

### API ReportCollector

```python
class ReportCollector:
    # Инициализация
    def __init__(self, *, run_id: str, command: str, started_at: datetime, items_limit: int = 1000) -> None

    # Установка метаданных (вызывается один раз)
    def set_meta(self, *, dataset: str | None, app_version: str | None, git_rev: str | None) -> None

    # Установка контекстного блока
    def set_context(self, name: str, value: dict) -> None

    # Регистрация операции (create/update/skip/etc)
    def add_op(self, name: str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None

    # Регистрация результата строки
    def add_item(self, *, status: str, row_ref, payload, errors, warnings, meta, store: bool) -> None

    # Финализация (stamps finished_at, duration_ms)
    def finish(self) -> None

    # Сборка финального объекта
    def build(self) -> ReportEnvelope
```

---

## 💡 Типичные сценарии

### Сценарий 1: Успешный прогон с одной ошибкой

```python
report = ReportCollector(run_id="xyz", command="import", started_at=now())
report.set_meta(dataset="employees", app_version="1.0.0", git_rev="abcdef")

# Строка 1 — OK
report.add_item(status="OK", row_ref=ref1, payload=row1, errors=[], warnings=[], meta={}, store=False)

# Строка 2 — FAILED
report.add_item(
    status="FAILED",
    row_ref=ref2,
    payload=None,
    errors=[ReportDiagnostic(severity="error", stage="MATCH", code="no_match", ...)],
    warnings=[],
    meta={"match_key": "employee_id"},
    store=True,  # FAILED строки всегда сохраняются
)

report.finish()
envelope = report.build()
# envelope.status == "PARTIAL" (есть и OK и FAILED)
# envelope.summary.rows_total == 2
# envelope.summary.rows_blocked == 1
# len(envelope.items) == 1  (только FAILED хранится)
```

---

### Сценарий 2: Превышение items_limit

```python
report = ReportCollector(run_id="xyz", command="import", started_at=now(), items_limit=3)

for i in range(10):
    report.add_item(status="FAILED", row_ref=..., errors=[...], store=True)

report.finish()
envelope = report.build()
# len(envelope.items) == 3          (лимит)
# envelope.meta.items_truncated == True
# envelope.summary.rows_blocked == 10  (счётчики полные!)
```

---

### Сценарий 3: Установка context-блоков из разных стадий

```python
# В report_writer:
report.set_context("config", {"config_sources": ["/etc/ankey/app.yaml"]})

# В команде import:
report.set_context("input", {"dataset": "employees", "source_file": "data.csv", "record_count": 500})

# В cache_refresh_service:
report.set_context("cache_refresh", {"refreshed": 12, "failed": 0})

# В finalizeReport():
report.set_context("runtime", {"duration_ms": 3200, "log_file": "logs/abc.log"})
```

---

## 📌 Важные детали

### Особенности реализации

- **`items_truncated` не влияет на счётчики**: `rows_total`, `rows_blocked`, `rows_with_warnings` — всегда полные, независимо от `items_limit`. Только `errors_total` / `warnings_total` / `by_stage` в summary считаются из хранимых items и могут быть занижены при truncation.
- **`finish()` нужно вызвать перед `build()`**: Без `finish()` поля `finished_at` и `duration_ms` в meta будут `None`.
- **`add_op()` аккумулирует**: Повторные вызовы с тем же `name` добавляют к существующим счётчикам, не перезаписывают.
- **`set_context()` перезаписывает**: Последнее значение для данного ключа wins.
- **Секретные поля в payload**: `payload` в `ReportItem` передаётся уже после `maskSecretsInObject()`, применённого в `TransformResultProcessor`. Дополнительная маскировка на уровне collector не выполняется.

### 🚨 Failure Modes

| Ситуация | Поведение | Как обработать |
|----------|-----------|---------------|
| `build()` до `finish()` | `finished_at=None`, `duration_ms=None` в meta | Всегда вызывать `finish()` перед `build()` (гарантирует `report_writer.finalizeReport()`) |
| `items_limit=0` | Все items отбрасываются, `items_truncated=True` с первой же записи | Не передавать `items_limit=0`; default=1000 |
| `set_context()` с одним ключом дважды | Последнее значение перезаписывает | Ожидаемое поведение; разные стадии должны использовать разные ключи |
| `add_item()` с `store=True` после `items_truncated=True` | Item отбрасывается; счётчики инкрементируются | Нормальный режим при большом датасете |

### ⚠️ Инварианты системы

1. **Инвариант: Счётчики всегда полные**
   - **Что**: `summary.rows_total == rows_passed + rows_blocked` всегда, независимо от `items_limit`.
   - **Почему важно**: Внешние системы мониторинга читают summary для оценки успешности прогона.
   - **Где проверяется**: `add_item()` всегда инкрементирует счётчики до проверки `_should_store_item()`.

2. **Инвариант: Envelope неизменяем после build()**
   - **Что**: После `build()` возвращённый `ReportEnvelope` не мутируется.
   - **Почему важно**: JSON-сериализация должна быть детерминированной.
   - **Где проверяется**: `build()` возвращает новый объект с копиями коллекций (`list(self._items)`, `dict(self._context)`).

3. **Инвариант: Секреты замаскированы в payload**
   - **Что**: Поля из `secret_fields` в `ReportItem.payload` заменены на `"***"`.
   - **Почему важно**: Отчёт пишется на диск и может быть прочитан без доступа к vault.
   - **Где проверяется**: `TransformResultProcessor.process()` применяет маскировку до передачи payload в `add_item()`.

4. **Инвариант: status из _derive_status(), если ApplyReportPresenter не вмешивается**
   - **Что**: Статус envelope всегда выводится из stored items через `_derive_status()`, если `ApplyReportPresenter` не установил `collector.status` напрямую.
   - **Почему важно**: Консистентность между summary и итоговым статусом.

### ⏱️ Performance заметки

**Узкие места**:
- `_count_diagnostics()` в `build()` итерирует все хранимые items и их диагностики. При `items_limit=1000` и ~10 диагностиках на item: до 10K итераций на `build()` — незначительно.
- `asdict_report()` выполняет глубокое копирование всего envelope; для типичного объёма (1000 items × ~5 полей) — несколько миллисекунд.

**Оптимизации**:
- Items хранятся в `list`, не в deque — `O(1)` append, `O(n)` copy при `build()`.
- `by_stage` строится за один проход в `_count_diagnostics()`.
- Нет индексирования по run_id или status — collector предназначен только для линейного накопления и одноразовой финализации.

---

## 🛠️ Как расширять

### Добавить новое поле в ReportMeta

1. Добавить поле в `ReportMeta` dataclass в `connector/domain/reporting/models.py`:
   ```python
   @dataclass
   class ReportMeta:
       ...
       new_field: str | None = None     # описание нового поля
   ```

2. Установить значение в `ReportCollector.set_meta()` или через новый метод.

3. Проверить, что `asdict_report()` включает поле — если `ReportMeta` — это обычный dataclass без `__slots__`, сериализация через `dataclasses.asdict()` подхватит поле автоматически.

### Добавить новый context-блок

Никаких изменений в collector не требуется — достаточно вызвать:
```python
report.set_context("my_stage", {"key": "value"})
```
из обработчика команды или сервиса. Ключ появится в `envelope.context` и в JSON-файле.

### Добавить новый тип операции в ops

```python
# В обработчике apply:
report.add_op("delete", ok=5, failed=0, count=5)
```
Новый ключ `"delete"` появится в `summary.ops` автоматически.

---

## 🔁 Жизненный цикл ReportCollector — полная диаграмма

```
┌─────────────────────────────────────────────────────────────────┐
│              ReportCollector lifecycle                          │
│                                                                 │
│  ① createEmptyReport()                                          │
│     ReportCollector(run_id, command, started_at)                │
│     set_context("config", ...)                                  │
│            │                                                    │
│            ▼                                                    │
│  ② Handler вызывается с report:                                 │
│     set_meta(dataset, app_version, git_rev)                     │
│     set_context("input", ...)                                   │
│            │                                                    │
│            ▼                                                    │
│  ③ Pipeline stages (цикл по строкам):                           │
│     ┌─────────────────────────────────┐                         │
│     │  TransformResultProcessor       │                         │
│     │    .process(result)             │ ← per row               │
│     │    → add_item(status, ...)      │                         │
│     └─────────────────────────────────┘                         │
│     .finalize() → set_context("normalize"/"enrich"/...)         │
│            │                                                    │
│            ▼                                                    │
│  ④ Apply stage:                                                 │
│     ApplyReportPresenter.present(result, collector, ...)        │
│     → add_op("create"/"update"/...)                             │
│     → collector.status = "PARTIAL"|"SUCCESS"|"FAILED"           │
│            │                                                    │
│            ▼                                                    │
│  ⑤ finalizeReport():                                            │
│     set_context("runtime", ...)                                 │
│     report.finish()   ← stamps finished_at, duration_ms         │
│            │                                                    │
│            ▼                                                    │
│  ⑥ writeReportJson():                                           │
│     report.build()    ← → ReportEnvelope (snapshot)            │
│     asdict_report()   ← → dict                                  │
│     json.dump()       ← → {report_dir}/{run_id}.json           │
└─────────────────────────────────────────────────────────────────┘
```

### Состояния ReportCollector

| Состояние | Когда | Допустимые операции |
|-----------|-------|---------------------|
| **Создан** | После `__init__()` | `set_meta()`, `set_context()`, `add_op()`, `add_item()` |
| **Накопление** | Во время pipeline | То же + `add_item()` в цикле |
| **Завершён** | После `finish()` | `build()` (только чтение) |
| **Зафиксирован** | После `build()` | — (envelope неизменяем) |

Нет явной проверки состояния — вызов `add_item()` после `finish()` технически допустим, но `finished_at` уже зафиксирован. Порядок вызовов обеспечивается архитектурой lifecycle (`run_with_report()`).

### Связи между моделями

```
ReportEnvelope
  ├── meta: ReportMeta
  │      └── run_id, command, started_at, finished_at, duration_ms,
  │          items_limit, items_truncated, app_version, git_rev
  ├── summary: ReportSummary
  │      └── rows_total, rows_passed, rows_blocked, rows_with_warnings,
  │          errors_total, warnings_total,
  │          by_stage: dict[str, int],
  │          ops: dict[str, dict[str, int]]
  ├── items: list[ReportItem]
  │      └── status, row_ref: RowRef,
  │          payload: dict | None,
  │          diagnostics: list[ReportDiagnostic],
  │          meta: dict | None
  │               └── ReportDiagnostic:
  │                     severity, stage, code, field, message, rule, details
  └── context: dict[str, dict]
         └── "config", "input", "runtime", "apply",
             "enrich", "normalize", "cache_refresh", "dictionary"
```

---

## ❓ FAQ

### Почему `errors_total` в summary может быть меньше реального числа ошибок?

`errors_total` и `warnings_total` в `ReportSummary` подсчитываются из хранимых `ReportItem`-объектов (`_count_diagnostics()` в `build()`). Если `items_truncated=True`, часть items не хранится → счётчики в summary занижены. `rows_blocked` (количество FAILED-строк) при этом остаётся точным, так как инкрементируется в `add_item()` вне зависимости от `store`.

**Рекомендация**: Для мониторинга используйте `summary.rows_blocked`, а не `summary.errors_total`.

---

### Можно ли получить финальный JSON без записи на диск?

Да. Вызовите `report.finish()`, затем `report.build()` для получения `ReportEnvelope`, затем `asdict_report(envelope)` для получения словаря. Функция `writeReportJson()` — это лишь тонкая обёртка над этой последовательностью.

```python
report.finish()
envelope = report.build()
data = asdict_report(envelope)
# data — обычный Python dict, готовый к json.dumps()
```

---

### Что происходит при `build()` до `finish()`?

`build()` не проверяет, был ли вызван `finish()`. Если `finish()` не вызван, `meta.finished_at` и `meta.duration_ms` будут `None` в возвращённом `ReportEnvelope`. JSON-файл будет содержать `"finished_at": null` и `"duration_ms": null`.

---

### Почему `_derive_status()` работает из items, а не из summary-счётчиков?

`summary.rows_blocked` корректен, но не отражает полную картину — `rows_blocked > 0` не обязательно означает `FAILED` (может быть `PARTIAL`). `_derive_status()` проверяет комбинацию: есть ли хотя бы один OK и хотя бы один FAILED среди хранимых items. Это точнее, чем простая проверка счётчиков.

**Исключение**: `ApplyReportPresenter` устанавливает `collector.status` напрямую, обходя `_derive_status()`, так как знает итог из `ApplyResult.summary`.

---

### Как items_limit влияет на использование памяти?

`ReportCollector` хранит items в `list[ReportItem]`. При `items_limit=1000` и ~5 диагностиках на item: приблизительно 1000 × (RowRef + dict payload + list diagnostics) = несколько МБ. Это ожидаемо для in-memory builder.

При `items_limit=0` items не хранятся вообще, но `build()` всё равно выполняет `_count_diagnostics([])` → `errors_total=0`. Не используйте `items_limit=0` без явной причины.

---

### Зачем нужна отдельная ReportDiagnostic если уже есть DiagnosticItem?

`DiagnosticItem` — это domain-объект конвейера, который может содержать ссылки на внутренние типы (enum-поля, специфичные для стадии атрибуты). `ReportDiagnostic` — сериализуемый value object без enum-зависимостей (severity, stage — строки). Такое разделение позволяет изменять внутреннее представление диагностики в конвейере без изменения JSON-формата отчёта.

---

## 🧪 Тестирование

### Unit-тесты ReportCollector

Типичная структура unit-тестов:

```python
def test_report_collector_status_partial():
    report = ReportCollector(run_id="test-1", command="import", started_at=datetime.now())

    # Добавляем OK и FAILED строки
    report.add_item(status="OK", row_ref=None, payload=None, errors=[], warnings=[], meta={}, store=True)
    report.add_item(status="FAILED", row_ref=None, payload=None, errors=[
        ReportDiagnostic(severity="error", stage="ENRICH", code="test_error", field=None, message="err")
    ], warnings=[], meta={}, store=True)

    report.finish()
    envelope = report.build()

    assert envelope.status == "PARTIAL"
    assert envelope.summary.rows_total == 2
    assert envelope.summary.rows_passed == 1
    assert envelope.summary.rows_blocked == 1
    assert envelope.summary.errors_total == 1
    assert envelope.summary.by_stage == {"ENRICH": 1}


def test_report_collector_items_truncation():
    report = ReportCollector(run_id="test-2", command="import", started_at=datetime.now(), items_limit=2)

    for _ in range(5):
        report.add_item(status="FAILED", row_ref=None, payload=None, errors=[], warnings=[], meta={}, store=True)

    report.finish()
    envelope = report.build()

    assert len(envelope.items) == 2           # лимит
    assert envelope.meta.items_truncated is True
    assert envelope.summary.rows_blocked == 5  # полный счётчик


def test_report_collector_context_overwrite():
    report = ReportCollector(run_id="test-3", command="import", started_at=datetime.now())
    report.set_context("config", {"v": 1})
    report.set_context("config", {"v": 2})  # перезаписывает

    report.finish()
    envelope = report.build()
    assert envelope.context["config"]["v"] == 2
```

### Тестирование asdict_report()

```python
def test_asdict_report_serializable():
    import json
    report = ReportCollector(run_id="test", command="test", started_at=datetime.now())
    report.finish()
    envelope = report.build()
    data = asdict_report(envelope)

    # Должен быть полностью JSON-сериализуемым
    json_str = json.dumps(data)
    assert json_str is not None
    parsed = json.loads(json_str)
    assert parsed["status"] == "SUCCESS"
    assert parsed["summary"]["rows_total"] == 0
```

### Тестирование summary.ops

```python
def test_add_op_accumulates():
    report = ReportCollector(run_id="test", command="apply", started_at=datetime.now())
    report.add_op("create", ok=5, failed=0, count=5)
    report.add_op("create", ok=3, failed=1, count=4)  # накапливается!

    report.finish()
    envelope = report.build()
    assert envelope.summary.ops["create"]["ok"] == 8
    assert envelope.summary.ops["create"]["failed"] == 1
    assert envelope.summary.ops["create"]["count"] == 9
```

---

## 🔗 Связанные документы

- [report-pipeline.md](./report-pipeline.md) — как стадии конвейера передают данные в ReportCollector
- [report-delivery.md](./report-delivery.md) — CLI lifecycle, I/O артефактов, JSON-формат вывода
- [vault-core.md](../vault/vault-core.md) — секретные поля в pipeline (связь с secret_candidate_fields в meta)
- [dictionary-core.md](../dictionary/dictionary-core.md) — dictionary telemetry в context["dictionary"]

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ | xORex-LC |
