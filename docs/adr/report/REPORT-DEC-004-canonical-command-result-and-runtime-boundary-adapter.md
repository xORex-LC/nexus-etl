# REPORT-DEC-004: Канонический DomainCommandResult и boundary-адаптер runtime

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-004
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Runtime сегодня поддерживает несколько result-контрактов (`DomainCommandResult`, `CliCommandResult`, `int`), что раздувает orchestration и усложняет консистентность report/exit semantics.

Для изоляции report-слоя и декомпозиции runtime нужен единый канонический результат команды.

---

## 🎯 Решение

Принять следующие правила:

1. Канонический результат команды — `connector.domain.diagnostics.command_result.CommandResult`.
2. Runtime report mapping работает только с canonical domain result.
3. `CliCommandResult` и `int` поддерживаются только через boundary-адаптер на переходный период.
4. UseCase формирует `CommandResult` через policy-резолверы (в т.ч. `StageCommandResultResolver` из [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)).
5. После миграционного окна compatibility paths удаляются.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/delivery/cli/result_adapter.py`
  - `to_domain_result(value: DomainCommandResult | CliCommandResult | int | None) -> DomainCommandResult | None`

**Изменения в существующих компонентах**:
- `connector/delivery/cli/runtime.py`
  - normalizes handler/lifecycle results к `DomainCommandResult` до report mapping;
  - сохраняет legacy ветки только через адаптер.
- `connector/delivery/commands/*`
  - постепенно возвращают `DomainCommandResult` напрямую.
- `connector/usecases/*`
  - единая policy-конвертация доменных исходов в `DomainCommandResult`.

### Интерфейсы

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
handler/usecase result
      ↓
result_adapter.to_domain_result(...)
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
- ⚠️ На переходе сохраняется adapter-слой и временная dual-совместимость.

**Альтернативы, которые отклонили**:
- ❌ **Сохранить dual-model навсегда**: закрепляет техдолг в runtime.
- ❌ **Only-int contract**: теряет богатую диагностику и переносит бизнес-семантику в runtime.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/result_adapter.py` | Новый boundary-адаптер в canonical result |
| `connector/delivery/cli/runtime.py` | Единый canonical path result->report |
| `connector/delivery/commands/*` | Возврат `DomainCommandResult` |
| `tests/unit/delivery/*` | Тесты адаптера и canonical path |

### Ключевые методы

- `to_domain_result(...)`
- `_exit_code_from_result(...)` (работает на canonical result)
- runtime result->report mapper (после normalization)

### Инварианты

1. **Canonical result model**: внутри runtime/report pipeline используется только `DomainCommandResult`.
2. **Boundary adaptation only**: legacy формы разрешены только на boundary-адаптере.
3. **Deterministic exit/report semantics**: одинаковый `DomainCommandResult` даёт одинаковый exit/report outcome.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: `to_domain_result()` корректно нормализует `DomainCommandResult`, `CliCommandResult`, `int`, `None`.
- ✅ Unit: runtime mapping использует только canonical result после normalization.
- ✅ Unit: synthetic diagnostics формируются детерминированно.
- ✅ Integration: команды возвращают согласованные report diagnostics и exit codes.
- ✅ Regression: удаление дублирующих веток обработки после миграции.

**Проверка в runtime**:
1. Прогнать успешные и failing сценарии (`mapping`, `enrich`, `resolve`, `import-apply`).
2. Сравнить report diagnostics и exit code до/после нормализации.
3. Подтвердить, что новые handlers не используют `CliCommandResult`.

**Метрики успеха**:
- Количество runtime-веток result mapping сокращено до canonical path + adapter.
- Доля команд, возвращающих `CliCommandResult`, стремится к 0.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Sequence Diagram](../../uml/pipeline/report_layer/report_layer_sequence.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- На миграции временно поддерживаются legacy формы результата.

**Риски**:
- ⚠️ Неполная миграция handler-ов сохранит скрытые compatibility ветки  
  → **Митигация**: deprecation план + контрактные тесты.
- ⚠️ Ошибки нормализации в adapter могут изменить exit semantics  
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
