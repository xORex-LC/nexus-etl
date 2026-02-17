# TARGET-DEC-002: Apply use-case возвращает ApplyResult, а отчёт формируется презентером

> **Статус**: Принято / реализовано
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

До решения `ImportApplyService` смешивал orchestration и output/infrastructure concerns:
- use-case формировал/мутировал отчётные структуры;
- были infra-зависимости и сайд-эффекты, не относящиеся к application logic;
- формат output фактически диктовал дизайн use-case.

Это ухудшало переиспользуемость use-case и мешало дальнейшей очистке target/load слоя.

См. [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md).

---

## 🎯 Решение

Разделить ответственность между use-case и delivery через response model + presenter.

Ключевые пункты:

1. `ImportApplyService.apply_plan(...)` возвращает `ApplyResult`.
2. Use-case не зависит от `ReportCollector` и не импортирует `connector.infra.*`/`connector.delivery.*`.
3. Преобразование `ApplyResult -> ReportCollector` выполняется в `ApplyReportPresenter`.
4. Per-item observability use-case реализуется через порт `ApplyTelemetrySink`.
5. Итоговый `CommandResult` строится в команде из `ApplyResult.primary_code/all_codes`.
6. Детализация item-outcomes ограничивается `max_item_outcomes` (пробрасывается из CLI `report_items_limit`).

---

## 🏗️ Архитектурное решение

### Компоненты

| Компонент | Назначение | Файл |
|-----------|------------|------|
| `ApplyResult` / `ApplySummary` / `ApplyItemOutcome` | typed response model use-case | `connector/usecases/apply/models.py` |
| `ImportApplyService` | orchestration apply-цикла | `connector/usecases/import_apply_service.py` |
| `ApplyTelemetrySink` | output-port событий apply | `connector/usecases/apply/telemetry.py` |
| `ApplyReportPresenter` | mapping результата use-case в отчёт | `connector/delivery/presenters/apply_report_presenter.py` |
| `LoggingApplyTelemetrySink` | delivery-реализация apply-телеметрии | `connector/delivery/telemetry/apply_logging_sink.py` |

### Интерфейс контракта (сокращённо)

```python
@dataclass(frozen=True)
class ApplyResult:
    summary: ApplySummary
    primary_code: SystemErrorCode
    all_codes: Tuple[SystemErrorCode, ...]
    fatal_error: bool
    item_outcomes: Tuple[ApplyItemOutcome, ...]
    outcomes_truncated: bool
```

### Поток данных

```
Plan -> ImportApplyService -> ApplyResult
                     -> ApplyReportPresenter -> ReportCollector
                     -> delivery command -> CommandResult
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ use-case остаётся чистым orchestration-компонентом;
- ✅ проще unit-тестировать бизнес-результат, не завязываясь на report structure;
- ✅ output-политика и формат отчёта изолированы в delivery;
- ✅ телеметрию можно эволюционировать через порт без изменения use-case контракта.

**Компромиссы**:
- ⚠️ появляется дополнительный слой адаптации (presenter);
- ⚠️ нужно поддерживать синхронность контрактов `ApplyResult` и reporting-модели.

**Отклонённые альтернативы**:
- ❌ оставить report внутри use-case и убрать только infra-импорты;
- ❌ сразу перейти на исключительно event-stream output без response model.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/usecases/import_apply_service.py` | use-case формирует и возвращает `ApplyResult` |
| `connector/usecases/apply/models.py` | введены response-модели apply |
| `connector/usecases/apply/telemetry.py` | введён output-port телеметрии |
| `connector/delivery/commands/import_apply.py` | команда строит `CommandResult` по `ApplyResult` |
| `connector/delivery/presenters/apply_report_presenter.py` | отчёт формируется на delivery-уровне |

### Этапы внедрения (фактически)

1. Контракт use-case переведён с report-side effects на `ApplyResult`.
2. В delivery добавлен presenter-слой для отчёта и отдельный telemetry sink.
3. Контракт итогового статуса команды переключён на `ApplyResult.primary_code/all_codes`.
4. Добавлены architecture/unit guard-тесты, чтобы закрепить разделение ответственности.

### Инварианты

1. Use-case не импортирует delivery/infra/datasets модули.
2. Use-case не зависит от `ReportCollector`.
3. `ApplyResult.summary` считается по всему обработанному плану.
4. `item_outcomes` ограничены `max_item_outcomes`, факт усечения фиксируется в `outcomes_truncated`.
5. `RecordRef` используется как нейтральная ссылка для корреляции item-результатов.
6. Per-item телеметрия идёт через `ApplyTelemetrySink`.

---

## 🧪 Валидация решения

- Архитектурные guard-тесты: `tests/architecture/test_apply_usecase_boundaries.py`.
- Unit use-case контракт:
  - `tests/unit/usecases/test_import_apply_result.py`
- Unit presenter контракт:
  - `tests/unit/delivery/test_apply_report_presenter.py`
- E2E сценарии apply pipeline:
  - `tests/e2e/pipelines/test_import_apply_pipeline.py`

---

## ⚠️ Риски и ограничения

- В текущем apply-потоке warning item-outcomes встречаются редко; основной поток outcomes покрывает error-сценарии.
- Presenter чувствителен к эволюции `ReportCollector`, поэтому требует обязательного unit-покрытия на изменение reporting-контракта.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `ImportApplyService` | Прямое | отказ от report/infra side-effects, возврат `ApplyResult` |
| Delivery command `import_apply` | Прямое | orchestration `use-case -> presenter -> command result` |
| Reporting layer | Косвенное | модель отчёта сохранена, изменён слой её заполнения |
| Observability | Косвенное | per-item логирование через delivery sink |

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md)
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md)
- [TARGET-DEC-003](./TARGET-DEC-003-target-core.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено и принято |
| 2026-02-13 | Выбрана модель `ApplyResult + Presenter` как базовый путь |
| 2026-02-14 | Реализован контракт `ImportApplyService -> ApplyResult` и delivery presenter |
| 2026-02-17 | ADR синхронизирован с финальной реализацией |
