# REPORT-DEC-006: Политика владения report meta и dataset boundary

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-006
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Поля `meta` заполняются в runtime, handlers и usecases одновременно. Это размывает ownership и приводит к семантическому шуму в `meta.dataset`.

---

## 🎯 Решение

Принять явную ownership policy для `ReportMeta`:

1. Владелец `items_limit` — runtime orchestration.
2. Владелец `dataset` — command handler (только dataset-aware команды).
3. Usecase-слой не вызывает `report.set_meta(...)`.
4. Runtime удаляет dataset fallback policy (`_resolve_dataset_opt`) для report meta.
5. Dataset-agnostic команды публикуют отчёт без `meta.dataset`.
6. Правило закрепляется архитектурным guard (tests + code review policy).

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/meta_policy.py`
  - `ReportMetaOwnershipPolicy`
  - `DatasetAwarenessPolicy`

**Изменения в существующих компонентах**:
- `connector/delivery/cli/runtime.py`
  - оставляет только runtime-owned meta поля.
- `connector/delivery/commands/*`
  - dataset-aware handlers выставляют `meta.dataset` явно.
- `connector/usecases/*`
  - больше не записывают `meta`.

### Интерфейсы

```python
class ReportMetaOwnershipPolicy(Protocol):
    def runtime_meta(self, *, items_limit: int) -> dict[str, Any]: ...
    def handler_meta(self, *, dataset: str | None) -> dict[str, Any]: ...
```

```python
class DatasetAwarenessPolicy(Protocol):
    def is_dataset_aware(self, command_name: str) -> bool: ...
```

### Поток данных

```
runtime -> set_meta(items_limit=...)
handler(dataset-aware) -> set_meta(dataset=...)
usecase -> no meta writes
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Чёткий owner для каждого поля `ReportMeta`.
- ✅ Устраняется конфликт между runtime/handler/usecase.
- ✅ Dataset semantics становится предсказуемой для consumers.
- ✅ Снижается связность usecase-слоя с report delivery concerns.

**Недостатки (компромиссы)**:
- ⚠️ Нужно обновить существующие usecases и тесты на ожидаемое поведение.
- ⚠️ Требуется явный список dataset-aware команд.

**Альтернативы, которые отклонили**:
- ❌ **Централизация всех meta полей в runtime**: runtime станет владельцем domain-семантики.
- ❌ **Сохранить текущий подход**: не устраняет drift ownership.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/runtime.py` | Удалить dataset fallback из meta policy |
| `connector/delivery/commands/*` | Явно выставлять dataset только в dataset-aware handlers |
| `connector/usecases/*` | Удалить вызовы `report.set_meta(...)` |
| `tests/unit/delivery/*` | Проверки ownership meta |
| `tests/unit/usecases/*` | Guard на отсутствие meta writes |

### Ключевые методы

- `run_with_report(...): report.set_meta(items_limit=...)`
- dataset-aware handlers: `report.set_meta(dataset=...)`

### Инварианты

1. `items_limit` всегда выставляется runtime.
2. `dataset` выставляется только handler-уровнем dataset-aware команд.
3. Usecase-слой не модифицирует `ReportMeta`.
4. Dataset-agnostic команды не публикуют `meta.dataset`.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Runtime всегда инициализирует `items_limit`.
- ✅ Dataset-aware команды выставляют `meta.dataset`.
- ✅ Dataset-agnostic команды оставляют `meta.dataset=None`.
- ✅ Usecases не содержат вызовов `report.set_meta(...)`.

**Проверка в runtime**:
1. Прогнать набор команд dataset-aware (`mapping`, `normalize`, `enrich`, `match`, `resolve`, `import-plan`, `import-apply`).
2. Прогнать dataset-agnostic (`check-api` и сценарии без dataset контракта).
3. Сверить отсутствие drift-перезаписи meta.

**Метрики успеха**:
- Количество точек записи `meta.items_limit` = 1 (runtime).
- Количество точек записи `meta.dataset` = только dataset-aware handlers.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Component Diagram](../../uml/pipeline/report_layer/report_layer_components.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Нужна синхронизация списка dataset-aware команд с delivery router.

**Риски**:
- ⚠️ Неполная миграция usecases может оставить скрытые `set_meta(...)`.
  - **Митигация**: grep-guard в тестовом наборе.
- ⚠️ Consumers могут ожидать dataset в каждом отчёте.
  - **Митигация**: документировать dataset-agnostic contract.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/cli/runtime.py` | Высокое | Очистить runtime meta policy |
| `connector/delivery/commands/*` | Среднее | Явно владеть dataset meta |
| `connector/usecases/*` | Высокое | Удалить report meta writes |
| `docs/dev/layers/report/*` | Среднее | Обновить описание meta ownership |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-006` и `REPORT-DEC-006`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-delivery.md`
  - `docs/dev/layers/report/report-models.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-006](./REPORT-PROBLEM-006-report-meta-ownership-drift-and-dataset-semantics.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
