# REPORT-DEC-002: Единый StageResultReporter и политика stage-result/CommandResult

> **Статус**: Принято
> **Дата принятия**: 2026-03-01
> **Решает проблему**: REPORT-PROBLEM-002
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

В `transform/core` закрепилась report-адаптерная логика с дублированием между `TransformResultProcessor` и `PlanningResultProcessor`.  
Перед реализацией крупного рефактора report layer нужно зафиксировать:

- единый canonical путь обработки row-results;
- чёткие границы ответственности между transform/usecase/reporting;
- policy для статусов stage-отчёта и вычисления `CommandResult`.

---

## 🎯 Решение

Принять следующую модель:

1. Ввести единый `StageResultReporter` (рабочее имя для реализации) вместо двух самостоятельных процессоров.
2. Использовать композицию:
   - `ExecutionStatsAccumulator`;
   - `PayloadSanitizer`;
   - `IStageReportStrategy`.
3. `PlanningResultProcessor` и `TransformResultProcessor` оставить как thin alias на 1 релиз, затем удалить.
4. Зафиксировать policy статуса как `stage-only`.
5. Формировать `CommandResult` на уровне usecase через `StageCommandResultResolver`.
6. Новый canonical owner: `connector/domain/reporting/adapters/*`.
7. Stage context schema — единая, immutable, без optional `None`.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/adapters/stage_result_reporter.py`
  - `StageResultReporter`
- `connector/domain/reporting/adapters/stats_accumulator.py`
  - `ExecutionStatsAccumulator`
  - `StageExecutionStats` (immutable snapshot)
- `connector/domain/reporting/adapters/payload_sanitizer.py`
  - `PayloadSanitizer`
- `connector/domain/reporting/adapters/strategies.py`
  - `IStageReportStrategy`
- `connector/domain/reporting/result_policy.py`
  - `StageCommandResultResolver`

**Изменения в существующих компонентах**:
- `connector/domain/transform/core/result_processor.py`
  - legacy alias-экспорт на переходный период (1 релиз).
- `connector/usecases/*`
  - переход на canonical reporter + `StageCommandResultResolver`.

### Интерфейсы

```python
class IStageReportStrategy(Protocol):
    def should_skip(self, result: TransformResult) -> bool: ...
    def build_payload(self, result: TransformResult) -> Mapping[str, Any] | None: ...
    def build_meta(
        self,
        result: TransformResult,
        *,
        upstream_errors_count: int,
        upstream_warnings_count: int,
    ) -> dict[str, Any]: ...


class StageResultReporter:
    def process(self, result: TransformResult | None, **kwargs: Any) -> None: ...
    def snapshot(self) -> StageExecutionStats: ...


class StageCommandResultResolver(Protocol):
    def resolve(self, stats: StageExecutionStats, **domain_flags: Any) -> CommandResult: ...
```

### Поток данных

```
TransformResult stream
      ↓
StageResultReporter.process()
      ├─ IStageReportStrategy (skip/payload/meta)
      ├─ PayloadSanitizer
      └─ ExecutionStatsAccumulator
      ↓
ReportCollector.add_item() + immutable stats snapshot
      ↓
UseCase -> StageCommandResultResolver.resolve(...)
      ↓
CommandResult
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Убирает дублирование `process()`-алгоритма.
- ✅ Разводит ответственности: report adaptation, stats, masking, бизнес-result policy.
- ✅ Упрощает тестирование через изолированные компоненты.
- ✅ Дает предсказуемый migration path без параллельной бизнес-логики.

**Недостатки (компромиссы)**:
- ⚠️ Нужен переходный период с alias-слоем.
- ⚠️ Потребуется обновление тестов и dev-документации под новый canonical API.
- ⚠️ Необходимо заранее стабилизировать schema consumers для нового context-контракта.

**Альтернативы, которые отклонили**:
- ❌ **Оставить две иерархии процессоров**: сохраняет DRY/SRP проблемы.
- ❌ **Runtime-owned business result mapping**: перегружает delivery runtime и ломает границы usecase-политик.
- ❌ **Usecase inline без resolver**: повышает шанс copy-paste политики `CommandResult` между usecases.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/reporting/adapters/stage_result_reporter.py` | canonical processor для stage-reporting |
| `connector/domain/reporting/adapters/stats_accumulator.py` | immutable snapshot статистики стадии |
| `connector/domain/reporting/adapters/payload_sanitizer.py` | выделение masking/security логики |
| `connector/domain/reporting/adapters/strategies.py` | strategy-контракты для stage различий |
| `connector/domain/reporting/result_policy.py` | `StageCommandResultResolver` |
| `connector/domain/transform/core/result_processor.py` | thin alias на 1 релиз |
| `connector/usecases/*` | применение canonical reporter и resolver |

### Ключевые методы

- `StageResultReporter.process(...)` — единая обработка row-result.
- `StageResultReporter.snapshot()` — immutable `StageExecutionStats`.
- `StageCommandResultResolver.resolve(...)` — единая policy-конвертация stage stats -> `CommandResult`.

### Инварианты

1. **Single processing algorithm**: алгоритм row-processing существует в одном canonical processor.
2. **Stage-only status policy**: `item.status` и `rows_blocked` зависят только от stage-local ошибок.
3. **Immutable stats/context contract**: snapshot и stage-context не мутируются после фиксации.
4. **No business logic in aliases**: legacy aliases только делегируют в canonical processor.

### Принятые assumptions/defaults

1. Фиксация выполняется отдельной новой парой ADR (`REPORT-PROBLEM-002` + `REPORT-DEC-002`).
2. Стратегия реализации — композиция + стратегии, не наследование как основной механизм.
3. `CommandResult` рассчитывается в usecase через resolver.
4. Legacy alias window ограничено 1 релизом.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: strategy behavior (`should_skip/build_payload/build_meta`).
- ✅ Unit: stage-only status policy (upstream diagnostics не ломают stage-статус).
- ✅ Unit: masking вынесен в `PayloadSanitizer`.
- ✅ Unit: `StageExecutionStats` snapshot immutable.
- ✅ Unit: `StageCommandResultResolver` одинаково вычисляет коды для старых и новых сценариев.
- ✅ Integration: parity отчётов для `normalize/mapping/enrich/match/resolve`.
- ✅ Regression: отсутствие дублирования `process()`-правил в двух классах.
- ✅ Compatibility: старые импорты `PlanningResultProcessor/TransformResultProcessor` работают в окно 1 релиз.

**Проверка в runtime**:
1. Прогнать команды `normalize`, `mapping`, `enrich`, `match`, `resolve`.
2. Сверить stage summary/status и context schema с целевым контрактом.
3. Подтвердить, что `CommandResult` формируется usecase resolver-ом, а не runtime.

**Метрики успеха**:
- Снижение числа мест, где меняется row-processing логика (один canonical модуль).
- Отсутствие расхождения stage-метрик между `match` и `resolve` при одинаковых условиях.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml)
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

**Примеры использования**:

```python
reporter = StageResultReporter(
    strategy=MatchStageReportStrategy(),
    stats=ExecutionStatsAccumulator(),
    sanitizer=PayloadSanitizer(),
)

for item in stream:
    reporter.process(item)

stats = reporter.snapshot()
result = stage_result_resolver.resolve(stats, has_conflicts=report.summary.errors_total > 0)
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- На переходном этапе одновременно существуют canonical processor и legacy aliases.
- Новая unified context schema требует синхронизации с потребителями отчёта.

**Риски**:
- ⚠️ Риск несовместимости consumer-ов context schema  
  → **Митигация**: заранее зафиксировать schema contract и обновить docs/consumers.
- ⚠️ Риск затяжного coexistence legacy aliases  
  → **Митигация**: зафиксировать removal window = 1 релиз.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/usecases/*` | Высокое | Переход на canonical reporter + `StageCommandResultResolver` |
| `connector/domain/transform/core` | Среднее | Удаление report-адаптерной логики, legacy alias only |
| `connector/domain/reporting/*` | Высокое | Новый owner adapter-логики row-result -> report item |
| `docs/dev/layers/report/*` | Среднее | Обновление contract/flow описаний под новую модель |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-002` и `REPORT-DEC-002`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-pipeline.md`
  - `docs/dev/layers/report/report-delivery.md`
  - `docs/dev/layers/report/report-models.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-002](./REPORT-PROBLEM-002-result-processor-duplication-and-boundary-leak.md)
- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)
- [REPORT-DEC-007](./REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-01 | Решение предложено |
| 2026-03-01 | Решение принято после обсуждения |
