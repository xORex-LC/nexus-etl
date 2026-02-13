# TARGET-DEC-002: Apply use-case возвращает ApplyResult, а отчёт формируется презентером (без report/infra в use-case)

> **Статус**: Предложено
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-002](./target/TARGET-PROBLEM-002-usecase-output-infra-leaks.md)
> **Участники решения**: @bernad

---

## 📋 Контекст

`ImportApplyService` (apply use-case) сейчас смешивает orchestration сценария с presentation/output и инфраструктурными деталями:

- use-case напрямую пишет в `ReportCollector` (meta/context/items/ops/summary);
- use-case вызывает `connector.infra.*` (например, infra logging);
- use-case опирается на runtime детали executor/клиента (например, retry stats).

Это размывает границы ответственности, усложняет тестирование и мешает “очистке load-слоя” вокруг `TargetRuntime/target-slice`.

См. [TARGET-PROBLEM-002](./target/TARGET-PROBLEM-002-usecase-output-infra-leaks.md).

---

## 🎯 Решение

Принять **вариант 2**:

1) Apply use-case (`ImportApplyService`) становится “чистым” orchestrator:
- выполняет plan-items через доменные порты (`RequestExecutorProtocol`, `ApplyRuntimePort`, `SecretProvider`);
- возвращает структурированный **ApplyResult** (response model) + `CommandResult`;
- принимает параметр `max_item_outcomes` (переиспользуем CLI `report_items_limit`) и возвращает ограниченный список item-outcome **только для ошибок и предупреждений** (severity `error`/`warning`), не более `max_item_outcomes`;
- **не** пишет в `ReportCollector`;
- **не** вызывает `connector.infra.*` и **не** интроспектит executor/клиент.

2) Формирование отчёта переносится в отдельный **презентер** (delivery-side adapter):
- `ApplyReportPresenter` принимает `ApplyResult` + runtime meta/stats (из `TargetRuntime`) + CLI options,
- заполняет доменный `ReportCollector` (reporting модель остаётся в домене).

3) Логирование/observability для apply (если нужно) выполняется в delivery/presenter слое, а не в use-case.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `ApplyResult` в `connector/usecases/apply/models.py`
  - summary counters, error_stats, системный код/фатальность
  - item outcomes **только для ошибок и предупреждений** (severity `error`/`warning`), ограничены `max_item_outcomes` (значение берём из CLI `report_items_limit`)
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
from typing import Mapping

from connector.domain.diagnostics import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import RowRef


@dataclass(frozen=True)
class ApplySummary:
    created: int
    updated: int
    failed: int
    skipped: int
    error_stats: Mapping[SystemErrorCode, int]


@dataclass(frozen=True)
class ApplyItemOutcome:
    row_ref: RowRef | None
    action: str  # CREATE|UPDATE|SKIP (semantics from PlanItem)
    target_id: str | None
    system_code: SystemErrorCode
    diagnostics: tuple[DiagnosticItem, ...]  # only warning/error items are included


@dataclass(frozen=True)
class ApplyResult:
    summary: ApplySummary
    fatal_error: bool
    system_code: SystemErrorCode

    # Ограниченный список исходов только для WARNING/ERROR (см. max_item_outcomes).
    item_outcomes: tuple[ApplyItemOutcome, ...]

    items_total: int
    items_included: int
```

### Поток данных

```
Plan → ImportApplyService → ApplyResult (+ CommandResult)
                 ↓
        ApplyReportPresenter
                 ↓
          ReportCollector
                 ↓
           ReportWriter/CLI
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Use-case остаётся чистым orchestrator сценария и зависит только от портов, а не от infra/output.
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
| `connector/domain/report/*` | Без изменений (остаётся модель отчёта) |

### Инварианты

1. Use-case не импортирует `connector.infra.*` и не вызывает infra-хелперы напрямую.
2. Use-case не принимает `ReportCollector` и не пишет в отчёт.
3. `TargetRuntime.stats()/meta()` добавляются в отчёт только в delivery/presenter слое.
4. `ApplyResult` не содержит raw payload и secret values.
5. `report_items_limit` переиспользуется как `max_item_outcomes` для ограничения item outcomes в `ApplyResult`.
6. В item outcomes включаются только элементы с диагностикой severity `error`/`warning`.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ unit: `ImportApplyService` возвращает корректный `ApplyResult.summary` для ok/fail сценариев (executor mock)
- ✅ unit: `ApplyReportPresenter` корректно заполняет `ReportCollector` по `ApplyResult`
- ✅ e2e: CLI `import_apply` формирует тот же смысловой отчёт, но без зависимости use-case от infra/output

**Метрики успеха**:
- `connector/usecases/import_apply_service.py` не содержит `report.` и `connector.infra.`
- `import_apply` команда не патчит executor/клиент для retries; использует `TargetRuntime.stats()`
- item-level детализация в отчёте формируется только из `ApplyResult.item_outcomes` (bounded by `max_item_outcomes`)

---

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

- [TARGET-PROBLEM-002](./target/TARGET-PROBLEM-002-usecase-output-infra-leaks.md) — решаемая проблема
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) — TargetRuntime/target-slice (контекст)
- [docs/adr](./README.md) — индекс ADR

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено: use-case возвращает ApplyResult, отчёт формирует presenter |
| 2026-02-13 | Выбран вариант 2 как базовый; вариант 3 отложен до необходимости потокового вывода |
