# REPORT-DEC-005: Декомпозиция runtime orchestrator и явный контракт handlers

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-005
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

`runtime.py` выполняет одновременно orchestration, invocation, compatibility-mapping и report finalization. Дополнительно dispatch handlers через `inspect.signature()` создаёт неявный API-контракт и усложняет миграцию к canonical result pipeline.

---

## 🎯 Решение

Принять следующие правила:

1. Убрать reflection dispatch (`inspect.signature`) из runtime.
2. Зафиксировать единый handler contract: `handler(ctx, opts, report_port)`.
   - `report_port` на этом этапе — переходный bridge (`ReportWritePort`) к конечной event-driven записи через `IReportSink` (`REPORT-DEC-001`/`REPORT-DEC-003`).
3. Декомпозировать runtime orchestration на отдельные ответственности:
   - lifecycle orchestration;
   - handler invocation;
   - result normalization/report mapping;
   - finalization/shutdown policy.
4. Оставить canonical path на `DomainCommandResult`.
5. Поддерживать `CliCommandResult` и `int` только через boundary adapter в окно совместимости 1 релиз, затем удалить.

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
  - canonical boundary adapter (legacy result normalization)

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
        report_port: ReportWritePort,  # transition bridge to IReportSink
    ) -> DomainCommandResult | None: ...
```

```python
def to_domain_result(
    value: DomainCommandResult | CliCommandResult | int | None,
    *,
    command_name: str,
    source: str,
) -> DomainCommandResult | None: ...
```

### Поток данных

```
run_with_report()
  -> runtime_orchestrator
  -> invoke CommandHandler(ctx, opts, report_port)
  -> result_adapter.to_domain_result(...)
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
- ✅ Compatibility-path локализован в boundary adapter.

**Недостатки (компромиссы)**:
- ⚠️ Переход требует миграции runtime tests и handler wiring.
- ⚠️ Временное coexistence legacy adapter path до удаления.

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
| `connector/delivery/cli/result_adapter.py` | Legacy normalization window |
| `tests/unit/delivery/test_runtime_*` | Контрактные и regression тесты |

### Ключевые методы

- `run_with_report(...)`
- `run_without_report(...)`
- `invoke_handler(...)`
- `to_domain_result(...)`
- `apply_domain_result_to_report(...)`

### Инварианты

1. Runtime вызывает только 3-arg handlers.
2. Reflection dispatch отсутствует.
3. Основной pipeline результата — `DomainCommandResult`.
4. Legacy result формы обрабатываются только в adapter-слое.
5. `report_port` в handler-контракте является bridge-only зависимостью до завершения migration-window и не отменяет целевой `IReportSink` boundary.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Runtime вызывает только 3-arg handlers.
- ✅ `inspect.signature` dispatch удалён.
- ✅ `CliCommandResult` и `int` проходят только через boundary adapter.
- ✅ Main path всегда работает на `DomainCommandResult`.

**Проверка в runtime**:
1. Прогнать `mapping`, `normalize`, `enrich`, `match`, `resolve`, `import-plan`, `import-apply`.
2. Проверить parity report/exit-code до и после декомпозиции.
3. Убедиться, что compatibility window ограничен 1 релизом.

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
- В migration window сохраняется legacy adapter path.
- В migration window `CommandHandler` сохраняет `ReportWritePort` как compatibility-bridge.

**Риски**:
- ⚠️ Неодновременная миграция handlers может временно ломать contract tests.
  - **Митигация**: feature-branch migration, общий contract test suite.
- ⚠️ Ошибки нормализации legacy результата могут повлиять на exit semantics.
  - **Митигация**: таблица parity-тестов по system codes.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/commands/*` | Высокое | Унифицировать handler contract |
| `connector/delivery/cli/runtime.py` | Высокое | Декомпозировать ответственности |
| `connector/delivery/cli/result_adapter.py` | Среднее | Локализовать compatibility-path |
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
