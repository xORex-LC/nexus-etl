# REPORT-DEC-005: Декомпозиция runtime orchestrator и явный контракт handlers

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-005
> **Участники решения**: @xORex-LC
> **Состояние реализации**: Завершено (2026-03-02), compatibility paths удалены

---

## 📋 Контекст

`runtime.py` выполняет одновременно orchestration, invocation, compatibility-mapping и report finalization. Дополнительно dispatch handlers через `inspect.signature()` создаёт неявный API-контракт и усложняет миграцию к canonical result pipeline.

---

## 🎯 Решение

Принять следующие правила:

1. Убрать reflection dispatch (`inspect.signature`) из runtime.
2. Зафиксировать единый handler contract: `handler(ctx, opts, report_sink)`.
   - `report_sink` реализует canonical event-driven ingestion через `IReportSink.emit(...)`.
3. Декомпозировать runtime orchestration на отдельные ответственности:
   - lifecycle orchestration;
   - handler invocation;
   - result normalization/report mapping;
   - finalization/shutdown policy.
4. Оставить canonical path на `DomainCommandResult`.
5. Поддерживать canonical path только на `DomainCommandResult`; compatibility windows для `CliCommandResult`/`int` удалены после release+1.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/delivery/cli/runtime_contracts.py`
  - `CommandHandler` protocol
  - `RuntimeLifecycleResult`
- `connector/delivery/cli/runtime_orchestrator.py`
  - orchestration use-flow (`run_with_report`, `run_without_report`) с делегированием
- `connector/delivery/cli/runtime_result_mapper.py`
  - mapping normalized result -> report items
- `connector/delivery/cli/result_adapter.py`
  - canonical runtime helpers для `DomainCommandResult` и exit-code policy

**Изменения в существующих компонентах**:
- `connector/delivery/cli/runtime.py`
  - становится thin facade, делегирующий в оркестратор/мэппер.
- `connector/delivery/commands/*`
  - все handlers поддерживают только 3-аргументный контракт.

### Интерфейсы

```python
class CommandHandler(Protocol):
    def __call__(
        self,
        ctx: BoundCommandContext,
        opts: Any,
        report_sink: IReportSink,
    ) -> DomainCommandResult | None: ...
```

```python
def exit_code_from_result(result: DomainCommandResult | None) -> int: ...
```

### Поток данных

```
run_with_report()
  -> runtime_orchestrator
  -> invoke CommandHandler(ctx, opts, report_sink)
  -> runtime_result_mapper.apply(...)
  -> finalize/shutdown policy
  -> exit-code policy
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Runtime становится предсказуемым orchestration boundary.
- ✅ Явный контракт handlers без reflection.
- ✅ Canonical result pipeline упрощает диагностику и testing.
- ✅ Runtime boundary использует только canonical `DomainCommandResult`.

**Недостатки (компромиссы)**:
- ⚠️ Переход требует миграции runtime tests и handler wiring.

**Альтернативы, которые отклонили**:
- ❌ **Сохранить `inspect.signature` dispatch**: оставляет неявный контракт.
- ❌ **Перенести mapping в handlers**: повышает дублирование.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/runtime.py` | Thin facade + delegating orchestration |
| `connector/delivery/cli/runtime_contracts.py` | Явный `CommandHandler` protocol |
| `connector/delivery/cli/runtime_orchestrator.py` | Разделение lifecycle шагов |
| `connector/delivery/cli/runtime_result_mapper.py` | Изолированный mapping result -> report |
| `connector/delivery/cli/result_adapter.py` | Canonical helper для `DomainCommandResult`/exit code |
| `tests/unit/delivery/test_runtime_*` | Контрактные и regression тесты |

### Ключевые методы

- `run_with_report(...)`
- `run_without_report(...)`
- `invoke_handler(...)`
- `exit_code_from_result(...)`
- `result_with(...)`
- `apply_domain_result_to_report(...)`

### Инварианты

1. Runtime вызывает только 3-arg handlers.
2. Reflection dispatch отсутствует.
3. Основной pipeline результата — `DomainCommandResult`.
4. Legacy result формы отсутствуют в runtime boundary.
5. Handler-контракт использует только `report_sink: IReportSink`.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Runtime вызывает только 3-arg handlers.
- ✅ `inspect.signature` dispatch удалён.
- ✅ Runtime boundary не принимает `CliCommandResult`/`int`.
- ✅ Main path всегда работает на `DomainCommandResult`.

**Проверка в runtime**:
1. Прогнать `mapping`, `normalize`, `enrich`, `match`, `resolve`, `import-plan`, `import-apply`.
2. Проверить parity report/exit-code до и после декомпозиции.
3. Подтвердить архитектурными guard-тестами отсутствие legacy runtime paths.

**Метрики успеха**:
- Количество branching-веток в runtime для result-dispatch сокращено до canonical + adapter path.
- Любая новая команда реализуется с единым handler interface.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)
- [Component Diagram](../../uml/pipeline/report_layer/report_layer_components.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Финализация отчёта остаётся в `run_with_report()` (`try/finally`) и не вынесена в middleware/decorator.

**Риски**:
- ⚠️ Ошибки в runtime result mapper могут повлиять на report/exit parity.
  - **Митигация**: unit/e2e regression suite на canonical result path.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/commands/*` | Высокое | Унифицировать handler contract |
| `connector/delivery/cli/runtime.py` | Высокое | Декомпозировать ответственности |
| `connector/delivery/cli/result_adapter.py` | Среднее | Поддерживать canonical helper-функции runtime result/exit policy |
| `tests/unit/delivery/*` | Высокое | Добавить contract + parity tests |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-005` и `REPORT-DEC-005`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-delivery.md`
  - `docs/dev/layers/report/report-pipeline.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-005](./REPORT-PROBLEM-005-runtime-orchestrator-overload-and-implicit-handler-contract.md)
- [REPORT-PROBLEM-004](./REPORT-PROBLEM-004-command-result-model-fragmentation.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-004](./REPORT-DEC-004-canonical-command-result-and-runtime-boundary-adapter.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
| 2026-03-02 | Завершен post-window cleanup: удалены compatibility paths (`CliCommandResult/int`) и bridge-контракт `ReportWritePort` |
