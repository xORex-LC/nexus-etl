# TARGET-DEC-002: Apply use-case возвращает ApplyResult, а отчёт формируется презентером (без report/infra в use-case)

> **Статус**: Предложено
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`ImportApplyService` (apply use-case) сейчас смешивает orchestration сценария с presentation/output и инфраструктурными деталями:

- use-case напрямую пишет в `ReportCollector` (meta/context/items/ops/summary);
- use-case вызывает `connector.infra.*` (например, infra logging);
- use-case опирается на runtime детали executor/клиента (например, retry stats).

Это размывает границы ответственности, усложняет тестирование и мешает “очистке load-слоя” вокруг `TargetRuntime/target-slice`.

См. [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md).

---

## 🎯 Решение

Принять **вариант 2**:

1) Apply use-case (`ImportApplyService`) становится “чистым” orchestrator:
- выполняет plan-items через доменные порты (`RequestExecutorProtocol`, `ApplyRuntimePort`, `SecretProvider`);
- возвращает структурированный **ApplyResult** (response model);
- `CommandResult` формируется в delivery из `ApplyResult.primary_code/all_codes` (единый источник истины по итоговому статусу);
- принимает параметр `max_item_outcomes` (переиспользуем CLI `report_items_limit`) и возвращает ограниченный список item-outcome **только для ошибок и предупреждений** (severity `error`/`warning`), не более `max_item_outcomes`;
- **не** пишет в `ReportCollector`;
- **не** вызывает `connector.infra.*` и **не** интроспектит executor/клиент.

2) Формирование отчёта переносится в отдельный **презентер** (delivery-side adapter):
- `ApplyReportPresenter` принимает `ApplyResult` + runtime meta/stats (из `TargetRuntime`) + CLI options,
- заполняет доменный `ReportCollector` (reporting модель остаётся в домене).

3) Логирование/observability для apply (если нужно) выполняется в delivery/presenter слое, а не в use-case.

---


### Уточнения (согласовано дополнительно)

- `SystemErrorCode` остаётся для **машинного результата запуска** (exit code, final system log/event, fatal classification), но **не попадает в apply-отчёт**.
- `ApplyResult.summary.error_stats` считается по **`diag.code`**, чтобы отчёт оставался “по строкам” и содержал конкретику.
- `fatal_error/primary_code/all_codes` **не управляют остановкой цикла apply** (основной режим: “пропусти строку и продолжай”). Эти поля используются только для **итогового статуса команды** и внешней интеграции (CLI/orchestrator).
- Вместо `RowRef` используем **`RecordRef`** как opaque reference. Apply берёт `record_ref` напрямую из `PlanItem` (или property), **не конструирует ref сам** и не зависит от source-структуры.
- Per-item логирование выполняется **без учёта `report_items_limit`** через output-port (`ApplyTelemetrySink`): use-case эмитит события на каждый item без payload/секретов (ERROR/WARN всегда, OK только DEBUG; INFO — только summary).
- Добавить архитектурный guard: `connector/usecases/*apply*` не импортирует `connector.infra.*`, `connector.delivery.*` и не обращается к `executor.client.*`.
- Контракт производительности: use-case считает `error_stats` по всему плану, но хранит item outcomes **в ограниченном буфере** `max_item_outcomes` (=`report_items_limit`), в порядке обработки; память не растёт от размера плана.

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `ApplyResult` в `connector/usecases/apply/models.py`
  - summary counters, error_stats, системный код/фатальность
  - item outcomes **только для ошибок и предупреждений** (severity `error`/`warning`), ограничены `max_item_outcomes` (значение берём из CLI `report_items_limit`)
- `ApplyTelemetrySink` (output-port) в `connector/usecases/apply/telemetry.py` (per-item события без payload)
- `ApplyReportPresenter` в `connector/delivery/presenters/apply_report_presenter.py`
  - преобразует ApplyResult → `ReportCollector`
  - добавляет `TargetRuntime.meta()/stats()` в context отчёта

**Изменения в существующих компонентах**:
- `connector/usecases/import_apply_service.py`:
  - перестать принимать/использовать `ReportCollector`
  - перестать вызывать `connector.infra.*`
  - перестать читать retry stats через executor/клиент
- `connector/delivery/commands/import_apply.py`:
  - вызывать use-case → получить `ApplyResult`
  - вызвать `ApplyReportPresenter` → получить заполненный `ReportCollector`

### Интерфейсы

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from connector.domain.diagnostics import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode


@dataclass(frozen=True)
class RecordRef:
    """Opaque correlation reference (no payload, no source schema)."""

    row_id: str
    line_no: int | None = None


@dataclass(frozen=True)
class ApplySummary:
    # Operation counters (human-facing)
    created: int
    updated: int
    failed: int
    skipped: int  # usually 0 for apply (plan items contain only create/update)

    # Totals (unbounded)
    items_total: int
    rows_with_warnings: int

    # Stats for apply report (diag.code -> count)
    error_stats: Mapping[str, int]


@dataclass(frozen=True)
class ApplyItemOutcome:
    # WARN/ERROR only (bounded by max_item_outcomes), in processing order.
    # status='OK' means warning-only item; status='FAILED' means item has errors.
    record_ref: RecordRef
    op: str  # 'create' | 'update' (same as PlanItem.op)
    status: str  # 'OK' | 'FAILED' (same semantics as ReportCollector.add_item)
    target_id: str | None
    diagnostics: Tuple[DiagnosticItem, ...]


@dataclass(frozen=True)
class ApplyResult:
    summary: ApplySummary

    # Machine outcome (for exit code + final system event)
    primary_code: SystemErrorCode
    all_codes: Tuple[SystemErrorCode, ...]
    fatal_error: bool

    # Bounded outcomes for reporting (WARN/ERROR only)
    item_outcomes: Tuple[ApplyItemOutcome, ...]
```

### Поток данных

```
Plan → ImportApplyService → ApplyResult
                 ↓
        ApplyReportPresenter
                 ↓
          ReportCollector
                 ↓
           ReportWriter/CLI
```


## 🧩 Реализация: паттерны, идиомы и языковые конструкции
### Паттерны

1. **Response Model + Presenter (Interface Adapter)**
   - Use-case возвращает `ApplyResult` (response model), не трогая `ReportCollector`.
   - `ApplyReportPresenter` (delivery-side adapter) преобразует `ApplyResult` → `ReportCollector` и применяет output-политику (verbosity/лимиты/формат).

2. **Output Port для телеметрии (Observer / Publisher–Subscriber)**
   - Use-case эмитит per-item события в интерфейс `ApplyTelemetrySink` (порт), не зная, куда они попадут.
   - Реализации:
     - `NullApplyTelemetrySink` (по умолчанию / в unit тестах)
     - `LoggingApplyTelemetrySink` (delivery/infra) — пишет структурированные логи.

3. **Decorator (опционально) для executor/runtime статистики**
   - Чтобы исключить `executor.client.*` в use-case, статистику попыток/ретраев собирать:
     - либо внутри infra-реализации executor,
     - либо через thin decorator `InstrumentedRequestExecutor`, который **сам реализует** `RequestExecutorProtocol` и публикует метрики через `TargetRuntime.stats()`.

### Python-механики

- `typing.Protocol` для портов (`ApplyTelemetrySink`, `RequestExecutorProtocol`) и простые реализации-адаптеры без фреймворков DI.
- `@dataclass(frozen=True)` для `ApplyResult`, `ApplyItemOutcome`, `RecordRef` — иммутабельные value objects, удобные в тестах.
- `logging.LoggerAdapter` или `logger.*(..., extra={...})` для структурного контекста (run_id, dataset, action, record_ref.row_id, record_ref.line_no).
- `contextlib.contextmanager` (опционально) для “span” вокруг обработки item (start/end) в `LoggingApplyTelemetrySink`, чтобы единообразно логировать успех/ошибку.
- Запрет на включение payload/secret values в любые логи/telemetry события и в `ApplyResult`/report.

### Мини-контракт для ApplyTelemetrySink (пример)

```python
from __future__ import annotations

from typing import Protocol

from connector.domain.diagnostics import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode


class ApplyTelemetrySink(Protocol):
    def on_item_ok(self, *, record_ref: RecordRef, op: str, target_id: str | None) -> None: ...
    def on_item_warn(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None: ...
    def on_item_error(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None: ...

    def on_summary(
        self,
        *,
        primary_code: SystemErrorCode,
        all_codes: tuple[SystemErrorCode, ...],
        fatal_error: bool,
        counters: ApplySummary,
    ) -> None: ...
```

Политика уровней:
- `ERROR/WARN` — всегда логировать per-item
- `OK` — логировать per-item только в `DEBUG`
- `INFO` — только `on_summary`


---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Use-case остаётся чистым orchestrator сценария и зависит только от портов, а не от infra/output.
- ✅ Отчёт остаётся “по строкам”: статистика и детализация строятся по `diag.code`, а системные коды остаются для машинного результата.
- ✅ Проще тестировать: unit тесты проверяют `ApplyResult`, не зависят от структуры отчёта.
- ✅ Use-case переиспользуем вне CLI (worker/scheduler/HTTP), т.к. он не “знает” о формате вывода.
- ✅ Отчёт остаётся доменной моделью (`ReportCollector`), но её заполнение — ответственность presenter/output-adapter.

**Недостатки (компромиссы)**:
- ⚠️ Появляется слой преобразования результата в отчёт (Presenter).
  - Приемлемо, потому что это локализует presentation/output и снимает нагрузку с use-case.
- ⚠️ Нужно решить уровень детализации item-level данных в `ApplyResult`.
  - Приемлемо, потому что на первом этапе достаточно summary + counts (без payload/secrets).

**Альтернативы, которые отклонили**:
- ❌ **Вариант 1 (report в use-case, только убрать infra)**: use-case всё равно смешивает orchestration и output → хуже переиспользуемость.
- ❌ **Вариант 3 (OutputPort/Observer streaming)**: возможно вернёмся, если потребуется потоковый вывод/очень большие планы; пока избыточно.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/usecases/apply/models.py` | Новый `ApplyResult`/`ApplySummary` |
| `connector/usecases/import_apply_service.py` | Возвращает `ApplyResult`, не пишет в report/infra |
| `connector/delivery/presenters/apply_report_presenter.py` | Новый presenter (ApplyResult → ReportCollector) |
| `connector/delivery/commands/import_apply.py` | Использует presenter для сборки отчёта |
| `connector/domain/reporting/*` | Без изменений (остаётся модель отчёта) |

### Инварианты

1. Use-case не импортирует `connector.infra.*` и не вызывает infra-хелперы напрямую.
2. Use-case не принимает `ReportCollector` и не пишет в отчёт.
3. `TargetRuntime.stats()/meta()` добавляются в отчёт только в delivery/presenter слое.
4. `ApplyResult` не содержит raw payload и secret values.
5. `report_items_limit` переиспользуется как `max_item_outcomes` в use-case; outcomes ограничиваются **на весь план** и сохраняются **в порядке обработки**.
6. Item-level outcomes возвращаются **только для WARN/ERROR**; `SKIP` не включается в outcomes и не отображается (только в summary).
7. Apply использует `RecordRef`, получая его из `PlanItem.row_id/line_no` через property/helper (например, `PlanItem.record_ref` как `@property`, без нового поля хранения).
8. Per-item логирование выполняется через output-port (`ApplyTelemetrySink`) и не зависит от лимитов отчёта; события не содержат payload/секретов.
9. `ApplySummary` и `primary_code/all_codes` считаются по всем обработанным plan-items, а не только по `item_outcomes`.
10. `ApplySummary.items_total` отражает число item с warning/error до лимита, а фактически вложенные элементы определяются как `len(item_outcomes)` после лимита.
11. `item_outcomes` содержит только операции `op in {'create', 'update'}` со статусами `status in {'OK', 'FAILED'}`; `SKIP` не включается (остаётся только в summary).


---


### Политика заполнения summary в ReportCollector

`ReportCollector.add_item()` инкрементирует `rows_total/rows_passed/rows_blocked/...` на каждый вызов.
Поскольку `ApplyResult.item_outcomes` содержит **только WARN/ERROR** (и ограничен лимитом),
`ApplyReportPresenter` **не должен** пытаться “восстановить” итоговую статистику через `add_item()`.

Рекомендация:
- Presenter выставляет итоговые счётчики **напрямую из `ApplyResult.summary`** (unbounded totals),
  а `add_item()` использует только для сохранения отображаемых элементов (WARN/ERROR) и выставления `items_truncated`.
- Если хочется избежать прямой мутации `collector.summary`, добавить thin-метод:
  `ReportCollector.apply_summary_from_apply_result(summary: ApplySummary)`.

Это гарантирует, что `status/rows_passed/rows_blocked` не будут искажены ограничением по items.


## 🧪 Валидация решения

**Unit**:
- ✅ `ImportApplyService` возвращает корректный `ApplyResult` (counters/totals/error_stats по `diag.code`, `fatal_error/primary_code/all_codes`) при ok/fail сценариях (executor mock).
- ✅ Лимит item outcomes: только WARN/ERROR, `max_item_outcomes` на весь план, порядок обработки, без SKIP.
- ✅ `ApplyTelemetrySink`: события эмитятся на каждый item; OK — только DEBUG; ERROR/WARN — всегда; без payload/секретов.
- ✅ `ApplyReportPresenter`: корректно переносит `ApplyResult` в `ReportCollector` (meta/context/summary/items), не добавляя `SystemErrorCode` в отчёт.

**Integration**:
- ✅ Apply + `SecretProvider` + vault-store: секрет извлекается только перед формированием `RequestSpec`, не попадает в `ApplyResult`/report/log payload.

**E2E**:
- ✅ CLI `import_apply`: формируется корректный отчёт и exit-code; в артефактах/логах нет секретов.

**Architecture guards**:
- ✅ Запрет импортов: `connector/usecases/*apply*` не импортирует `connector.infra.*` и `connector.delivery.*`, и не обращается к `executor.client.*`.

**Performance (pybench)**:
- ✅ 2–3 micro-bench теста (pyperf runner) на регрессии:
  - `bench_apply_usecase_summary_only`: apply на N items с OK результатами (проверить, что overhead не растёт с размером плана, память стабильна).
  - `bench_apply_usecase_warn_error_buffered`: N items с WARN/ERROR, проверить, что буфер outcomes ограничен `max_item_outcomes`.
  - `bench_presenter_build_report`: построение `ReportCollector` из `ApplyResult` с M outcomes.


## 📐 Диаграммы

- ⏳ UML (Sequence): `import_apply` → `ImportApplyService` → `ApplyReportPresenter` → `ReportCollector`
- ⏳ UML (Class): `ApplyResult` + `ApplyReportPresenter`

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- На первом шаге `ApplyResult` может включать item outcomes только для WARNING/ERROR, ограниченные `max_item_outcomes` (из CLI `report_items_limit`).
- При очень больших планах может понадобиться потоковый вывод (тогда рассматриваем вариант 3 — OutputPort).

**Риски**:
- ⚠️ Риск: presenter начнёт разрастаться и “тащить” бизнес-логику → **Митигация**: presenter только форматирует и перекладывает данные.
- ⚠️ Риск: несогласованность ожиданий отчёта между CLI и tests → **Митигация**: зафиксировать contract на уровне `ApplyResult` и presenter unit tests.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `ImportApplyService` | Упрощение и очистка границ | Удалить report/infra, вернуть ApplyResult |
| `import_apply` command | Тоньше по логике сценария, но добавляет вызов presenter | Создать report через presenter |
| Reporting (domain) | Нет | Модель отчёта не меняется |
| TargetRuntime | Косвенно | Статистика/мета добавляется в report в delivery |

---

## 📚 Документация

**Обновлена документация**:
- ⏳ `docs/dev/layers/apply/usecase-output-boundary.md` — границы use-case ↔ presenter ↔ report
- ⏳ Обновить ADR индекс (после принятия)

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-002](./TARGET-PROBLEM-002-usecase-output-infra-leaks.md) — решаемая проблема
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) — TargetRuntime/target-slice (контекст)
- [ADR INDEX](../INDEX.md) — индекс ADR

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено: use-case возвращает ApplyResult, отчёт формирует presenter |
| 2026-02-13 | Выбран вариант 2 как базовый; вариант 3 отложен до необходимости потокового вывода |
| 2026-02-14 | Рассмотрены дополнительные риски по SystemErrorCode/RowRef |
| 2026-02-14 | Добавлены инварианты на полноту `summary`/`system_codex` и семантику `items_total`/`items_include` |
| 2026-02-14 | Рассмотрены способы реализации |
