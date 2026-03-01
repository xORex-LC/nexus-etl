# REPORT-DEC-003: ReportWritePort и инкапсуляция ReportCollector

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-003
> **Участники решения**: @xORex-LC
> **Состояние реализации**: Завершено (2026-03-02), bridge удалён после release+1

---

## 📋 Контекст

`ReportCollector` используется как центральный аккумулятор отчёта, но часть компонентов обновляет его напрямую, обходя инварианты.  
Для надёжной изоляции report-слоя нужен единый write-boundary и запрет bypass-мутаций.
Этот шаг был зафиксирован как переходный слой совместимости до полного event-driven ingestion через `IReportSink` (`REPORT-DEC-001`); окно совместимости закрыто в post-window cleanup.

---

## 🎯 Решение

Принять следующие правила:

1. Ввести единый контракт записи `ReportWritePort`.
2. Разрешить запись в отчёт только через `ReportWritePort`/методы коллектора, но не через прямую мутацию полей.
3. Перевести `ApplyReportPresenter` и другие внешние writers на этот контракт.
4. Возвращать из `ReportCollector.build()` snapshot, исключающий пост-фактум мутацию собранного отчёта.
5. Добавить архитектурные guardrails (tests/lint rules) на запрет direct mutation вне `collector.py`.
6. Явно зафиксировать `ReportWritePort` как переходный bridge: целевой публичный API пополнения отчёта — `IReportSink.emit(...)`; после migration-window bridge удаляется.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/ports.py`
  - `ReportWritePort` (Protocol, transition bridge; удалён после release+1)
- `connector/domain/reporting/snapshots.py`
  - snapshot helpers для safe-build (или эквивалентная реализация внутри collector)

**Изменения в существующих компонентах**:
- `connector/domain/reporting/collector.py`
  - явная инкапсуляция write-операций;
  - `build()` возвращает snapshot, не “живые” mutable ссылки.
- `connector/delivery/presenters/apply_report_presenter.py`
  - migration-этап: через `ReportWritePort`; итоговый этап: через `IReportSink`, без прямой мутации `collector.summary/items/status/context`.

### Интерфейсы

```python
class ReportWritePort(Protocol):
    def set_meta(self, **kwargs: Any) -> None: ...
    def set_context(self, name: str, value: dict[str, Any]) -> None: ...
    def add_op(self, name: str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None: ...
    def add_item(self, *, status: str, row_ref: RowRef | None = None, payload: Mapping[str, Any] | None = None, errors: Iterable[ReportDiagnostic] | None = None, warnings: Iterable[ReportDiagnostic] | None = None, meta: dict[str, Any] | None = None, store: bool = True) -> None: ...
    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None: ...
```

### Поток данных

```
UseCase / Presenter / Runtime
        ↓
    ReportWritePort
        ↓
   ReportCollector (invariants owner)
        ↓
 build() -> immutable/safe snapshot
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Один write-path для всех producers отчёта.
- ✅ Инварианты summary/status сосредоточены в одном владельце.
- ✅ Снижение риска расхождения агрегатов.
- ✅ Подготовка к event-driven модели без параллельных путей записи.

**Недостатки (компромиссы)**:
- ⚠️ Нужна миграция существующих presenter/runtime участков.
- ⚠️ Появляется дополнительный порт/контракт, который нужно поддерживать.

**Альтернативы, которые отклонили**:
- ❌ **Оставить direct mutation**: не решает root-cause нарушения инвариантов.
- ❌ **Сразу удалить collector и перейти на event-only**: высокий риск одномоментной миграции.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/reporting/ports.py` | Исторический bridge-контракт `ReportWritePort` (удалён после release+1) |
| `connector/domain/reporting/collector.py` | Инкапсуляция write-path и snapshot build |
| `connector/delivery/presenters/apply_report_presenter.py` | Миграция с direct mutation -> bridge -> canonical `IReportSink` |
| `tests/unit/reporting/*` | Тесты инвариантов и snapshot-поведения |
| `tests/unit/delivery/*` | Тесты presenter без direct mutation |

### Ключевые методы

- `ReportWritePort.add_item(...)`
- `ReportWritePort.add_op(...)`
- `ReportCollector.build()` (snapshot semantics)

### Инварианты

1. **Single writer contract**: внешние компоненты не модифицируют collector state напрямую.
2. **Collector owns invariants**: только collector решает, как обновлять summary/status.
3. **Snapshot safety**: собранный envelope не мутируется обратно через разделяемые ссылки.
4. **Bridge-only role**: `ReportWritePort` не является конечным ingestion API и не расширяется новой event-семантикой после принятия `IReportSink`.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: `ReportCollector` сохраняет консистентность summary/status только через свой API.
- ✅ Unit: `build()` возвращает snapshot, изоляция от последующих мутаций writer-состояния.
- ✅ Unit: `ApplyReportPresenter` не выполняет direct mutation и пишет через canonical write boundary.
- ✅ Regression: устранение direct mutation паттернов в delivery presenters.

**Проверка в runtime**:
1. Выполнить `import-apply`, `mapping`, `enrich`.
2. Сверить, что summary/status совпадают с текущими контрактами.
3. Подтвердить отсутствие ручных прямых мутаций collector state вне owner-модуля.

**Метрики успеха**:
- Количество direct mutation мест (`collector.summary/*`, `collector.items.append`) вне collector равно 0.
- Изменения правил summary требуют правок только в `collector.py`.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml)
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Решение носило переходный характер до полного event-driven cutover.

**Риски**:
- ⚠️ Legacy код может снова добавить bypass-мутации  
  → **Митигация**: архитектурные тесты/grep-guard на direct mutation.
- ⚠️ Snapshot semantics может повлиять на существующие тесты с shared references  
  → **Митигация**: целевые regression tests и явная фиксация контракта.
- ⚠️ Риск затянуть bridge и сохранить два конкурирующих API записи  
  → **Митигация**: removal criterion в релиз-плане и запрет новых write-features вне `IReportSink`.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/presenters/apply_report_presenter.py` | Высокое | Убрать прямую мутацию collector state |
| `domain/reporting/collector.py` | Высокое | Инкапсулировать state + snapshot build |
| `delivery/cli/runtime.py` | Среднее | Использовать единый write-port контракт |
| `tests/*` | Среднее | Добавить guardrails для write-boundary |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-003` и `REPORT-DEC-003`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-models.md`
  - `docs/dev/layers/report/report-pipeline.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-003](./REPORT-PROBLEM-003-collector-encapsulation-and-write-port-gap.md)
- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-006](./REPORT-DEC-006-report-meta-ownership-policy-and-dataset-boundary.md)
- [REPORT-DEC-007](./REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
| 2026-03-02 | Завершен post-window cleanup: `ReportWritePort` bridge удалён, canonical ingestion работает через `IReportSink.emit(...)` |
