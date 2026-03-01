# REPORT-DEC-007: Report schema v2, typed context, nullable RowRef.line_no и skipped-reporting для import-plan

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-007
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Текущий report контракт не покрывает единообразно `SKIPPED`, truncate semantics, typed context keys и корректную передачу `line_no=None`. CLI обещает `--report-include-skipped`, но execution path import-plan это не реализует.

---

## 🎯 Решение

Принять report schema `v2.0` (breaking) со следующими изменениями:

1. `ReportMeta.schema_version = "2.0"`.
2. `ReportItem.status` расширяется: `OK | FAILED | SKIPPED`.
3. `ReportSummary` получает `rows_skipped`.
4. `RowRef.line_no` становится `int | None`.
5. `items_truncated=True` выставляется при любом непомещённом `store=True` item, независимо от status.
6. `context` и `summary.ops` переходят на typed keys/contracts (без ad-hoc magic string на верхнем уровне).
7. `import plan` полноценно поддерживает `--report-include-skipped` с фиксированным приоритетом:
   - `effective_include_skipped_items = policy.capabilities.include_skipped_items AND cli_include_skipped`;
   - `cli_include_skipped` — итоговое bool-значение после CLI/config resolution;
   - `true`: записывать `SKIPPED` row-items;
   - `false`: не хранить skipped row-items;
   - в обоих режимах `rows_skipped` в summary отражает факт skip;
   - plan artifact для `import apply` не включает skipped actions.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/schema_v2.py`
  - typed enums/status/context keys
  - `ReportSchemaVersion`
- `connector/domain/reporting/contracts.py`
  - typed contracts для `summary.ops` и `context` namespaces
- `connector/delivery/presenters/planning_report_presenter.py`
  - адаптер для публикации skipped-report items в `import-plan`

**Изменения в существующих компонентах**:
- `connector/domain/reporting/models.py`
  - v2 поля/типы: `schema_version`, `rows_skipped`, status union, nullable `line_no`.
- `connector/domain/reporting/collector.py`
  - status-independent truncate handling.
- `connector/delivery/commands/import_plan.py`
  - wiring `report_include_skipped` из CLI/config.
- `connector/delivery/cli/app.py`
  - передача `--report-include-skipped` в `import_plan.Options`.

### Интерфейсы

```python
class ReportItemStatus(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
```

```python
@dataclass
class ReportSummary:
    rows_total: int = 0
    rows_passed: int = 0
    rows_blocked: int = 0
    rows_skipped: int = 0
    rows_with_warnings: int = 0
```

```python
@dataclass(frozen=True)
class RowRef:
    line_no: int | None
    row_id: str
    identity_primary: str | None
    identity_value: str | None
```

### Поток данных

```
import-plan resolve stream
  -> plan builder (skip action excluded from plan file)
  -> planning_report_presenter
      -> add_item(status=SKIPPED, store=effective_include_skipped_items)
      -> summary.rows_skipped++
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Явный и версионированный schema contract.
- ✅ Прозрачная skipped semantics для CLI и consumers.
- ✅ Корректная передача неизвестного `line_no` без искажения в `0`.
- ✅ Предсказуемое поведение `items_truncated` для всех статусов.

**Недостатки (компромиссы)**:
- ⚠️ Breaking change для существующих consumers report JSON.
- ⚠️ Требуется миграция тестов и документации на schema v2.

**Альтернативы, которые отклонили**:
- ❌ **OK + `meta.op=skip` без нового status**: скрывает доменную семантику skip.
- ❌ **ops-only skipped без row-items**: недостаточная трассируемость.
- ❌ **Dual v1/v2 serialization**: удваивает поддержку и усложняет migration.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/models.py` | `RowRef.line_no: int | None` |
| `connector/domain/reporting/models.py` | schema v2 поля и типы |
| `connector/domain/reporting/collector.py` | truncate/status logic + skipped counters |
| `connector/delivery/cli/app.py` | wiring `report-include-skipped` |
| `connector/delivery/commands/import_plan.py` | `Options.report_include_skipped` + config fallback |
| `connector/delivery/presenters/apply_report_presenter.py` | удалить `line_no or 0` нормализацию |
| `tests/unit/reporting/*`, `tests/e2e/pipelines/*` | schema v2 + skipped scenarios |

### Ключевые методы

- `ReportCollector.add_item(...)`
- `ReportCollector.build()`
- `import_plan.handler(...)`

### Инварианты

1. `items_truncated` выставляется для любого непомещённого `store=True` item.
2. `SKIPPED` — first-class `item.status`.
3. `rows_skipped` отражает количество skip-событий независимо от хранения row-items.
4. `line_no=None` сохраняется без преобразования в `0`.
5. `import apply` не получает skipped actions из plan artifact.
6. CLI override не может расширять policy-capability: `true` в CLI не включает skipped items, если policy запретил их хранение.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `items_truncated=True` при переполнении для `SKIPPED`/`OK`/`FAILED`.
- ✅ `RowRef.line_no=None` сохраняется в report.
- ✅ `import plan --report-include-skipped=true` пишет `SKIPPED` items и `rows_skipped`.
- ✅ `import plan --no-report-include-skipped` не пишет skipped items, но summary сохраняет `rows_skipped`.
- ✅ При `policy.capabilities.include_skipped_items=false` `SKIPPED` items не пишутся даже если CLI override=true.
- ✅ Plan file для `import apply` не содержит skipped actions.
- ✅ Contract tests на typed `context`/`ops` keys.

**Проверка в runtime**:
1. Выполнить import-plan на данных с skip-сценариями.
2. Сравнить два режима include-skipped.
3. Проверить, что import-apply поведение unchanged по составу plan items.

**Метрики успеха**:
- CLI опция `--report-include-skipped` полностью соответствует фактическому output.
- Consumers читают versioned schema `2.0` без двусмысленностей.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml)
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Schema v2 требует синхронного обновления downstream consumers.

**Риски**:
- ⚠️ Breaking migration может временно нарушить интеграции.
  - **Митигация**: явный release note + migration guide.
- ⚠️ Неконсистентное внедрение typed keys между командами.
  - **Митигация**: shared contracts + contract tests.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/domain/reporting/*` | Высокое | Внедрить schema v2 |
| `connector/delivery/commands/import_plan.py` | Высокое | Wired include-skipped policy |
| `connector/delivery/presenters/*` | Среднее | Убрать `line_no` coercion и magic keys |
| `docs/dev/layers/report/*` | Высокое | Обновить contract и примеры JSON |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-007` и `REPORT-DEC-007`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-models.md`
  - `docs/dev/layers/report/report-pipeline.md`
  - `docs/dev/layers/report/report-delivery.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-007](./REPORT-PROBLEM-007-report-schema-v2-typed-context-and-skipped-contract-gap.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [REPORT-DEC-006](./REPORT-DEC-006-report-meta-ownership-policy-and-dataset-boundary.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
