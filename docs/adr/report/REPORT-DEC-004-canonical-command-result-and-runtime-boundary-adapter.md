# REPORT-DEC-004: Канонический DomainCommandResult и boundary-адаптер runtime

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-004
> **Участники решения**: @xORex-LC
> **Состояние реализации**: Завершено (2026-03-02), compatibility path удалён

---

## 📋 Контекст

Runtime сегодня поддерживает несколько result-контрактов (`DomainCommandResult`, `CliCommandResult`, `int`), что раздувает orchestration и усложняет консистентность report/exit semantics.

Для изоляции report-слоя и декомпозиции runtime нужен единый канонический результат команды.

---

## 🎯 Решение

Принять следующие правила:

1. Канонический результат команды — `connector.domain.diagnostics.command_result.CommandResult`.
2. Runtime report mapping работает только с canonical domain result.
3. `CliCommandResult` и `int` поддерживались только через boundary-адаптер в переходный период.
4. UseCase формирует `CommandResult` через policy-резолверы (в т.ч. `StageCommandResultResolver` из [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)).
5. После миграционного окна compatibility paths удаляются (выполнено).

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/delivery/cli/result_adapter.py`
  - `result_with(code: SystemErrorCode) -> DomainCommandResult`
  - `exit_code_from_result(result: DomainCommandResult | None) -> int`

**Изменения в существующих компонентах**:
- `connector/delivery/cli/runtime.py`
  - использует только canonical `DomainCommandResult` в runtime/report pipeline.
- `connector/delivery/commands/*`
  - постепенно возвращают `DomainCommandResult` напрямую.
- `connector/usecases/*`
  - единая policy-конвертация доменных исходов в `DomainCommandResult`.

### Интерфейсы

```python
def exit_code_from_result(result: DomainCommandResult | None) -> int: ...
```

### Поток данных

```
handler/usecase result
      ↓
DomainCommandResult (canonical)
      ↓
runtime report mapping + exit-code policy
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Один канонический контракт результата в системе.
- ✅ Упрощение runtime orchestration и снижение branching.
- ✅ Предсказуемая связь diagnostics/system codes/report status/exit code.
- ✅ Легче тестировать и развивать командные сценарии.

**Недостатки (компромиссы)**:
- ⚠️ Нужна этапная миграция delivery handlers.

**Альтернативы, которые отклонили**:
- ❌ **Сохранить dual-model навсегда**: закрепляет техдолг в runtime.
- ❌ **Only-int contract**: теряет богатую диагностику и переносит бизнес-семантику в runtime.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/result_adapter.py` | Canonical helper для runtime result/exit-code policy |
| `connector/delivery/cli/runtime.py` | Единый canonical path result->report |
| `connector/delivery/commands/*` | Возврат `DomainCommandResult` |
| `tests/unit/delivery/*` | Тесты адаптера и canonical path |

### Ключевые методы

- `exit_code_from_result(...)`
- `result_with(...)`
- `_exit_code_from_result(...)` (работает на canonical result)
- runtime result->report mapper (после normalization)

### Инварианты

1. **Canonical result model**: внутри runtime/report pipeline используется только `DomainCommandResult`.
2. **Boundary cleanup complete**: legacy формы удалены из runtime boundary.
3. **Deterministic exit/report semantics**: одинаковый `DomainCommandResult` даёт одинаковый exit/report outcome.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: runtime mapping использует только canonical result path.
- ✅ Unit: synthetic diagnostics формируются детерминированно.
- ✅ Integration: команды возвращают согласованные report diagnostics и exit codes.
- ✅ Regression: удаление дублирующих веток обработки после миграции.

**Проверка в runtime**:
1. Прогнать успешные и failing сценарии (`mapping`, `enrich`, `resolve`, `import-apply`).
2. Сравнить report diagnostics и exit code до/после нормализации.
3. Подтвердить архитектурными guard-тестами отсутствие legacy result paths.

**Метрики успеха**:
- Количество runtime-веток result mapping сокращено до canonical path + adapter.
- Доля runtime-веток для non-canonical результата равна 0.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Финализация отчёта остаётся в runtime orchestration (`run_with_report()`), без middleware-декомпозиции.

**Риски**:
- ⚠️ Ошибки в runtime result mapper могут изменить exit/report semantics  
  → **Митигация**: unit/e2e тесты на матрицу системных кодов и runtime paths.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/cli/runtime.py` | Высокое | Нормализация всех result форм в canonical domain result |
| `delivery/commands/*` | Среднее | Возврат `DomainCommandResult` |
| `usecases/*` | Среднее | Явное формирование system codes через resolver-политику |
| `tests/delivery/*` | Высокое | Покрытие canonical + adapter paths |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-004` и `REPORT-DEC-004`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-delivery.md`
  - `docs/dev/layers/report/report-pipeline.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-004](./REPORT-PROBLEM-004-command-result-model-fragmentation.md)
- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
| 2026-03-02 | Завершен post-window cleanup: runtime принимает только `DomainCommandResult | None`, compatibility path `CliCommandResult/int` удален |
