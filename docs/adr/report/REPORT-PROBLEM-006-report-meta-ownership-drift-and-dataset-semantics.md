# REPORT-PROBLEM-006: Дрейф владения report meta и неявная семантика dataset

> **Статус**: Закрыто
> **Дата создания**: 2026-03-02
> **Затронутые компоненты**: `runtime.py`, `delivery/commands/*`, `usecases/*`, `ReportCollector`

---

## 📋 Контекст

`meta` отчёта инициализируется в нескольких местах: runtime, handlers и usecase-слой. Это привело к drift-эффекту ownership-а и неоднородной семантике полей `dataset/items_limit`.

Дополнительно runtime выставляет dataset через fallback (`_resolve_dataset_opt`) даже для dataset-agnostic сценариев.

---

## ⚠️ Проблема

В report layer отсутствует единая policy по владельцам `meta`-полей.

Следствия:
- дублирование `set_meta(...)` в разных слоях;
- риск конфликтующих значений `dataset/items_limit`;
- ложная семантика: dataset может появляться в отчёте команд, которые не оперируют конкретным dataset.

---

## 🔍 Симптомы

- **Симптом 1**: runtime устанавливает `items_limit` и `dataset`, а handlers/usecases повторно задают те же поля.
- **Симптом 2**: usecases напрямую модифицируют report meta, хотя это boundary concern.
- **Симптом 3**: dataset-agnostic команды могут получить `meta.dataset` через runtime fallback.
- **Симптом 4**: отсутствуют guardrails на ownership meta-полей.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при эволюции runtime/command/usecase контрактов.
- **Критичность**: Высокая.
- **Затронуто**: Все команды с отчётами и консистентность downstream consumers.

---

## 🧪 Как воспроизвести

1. Запустить dataset-agnostic команду без явного dataset-параметра.
2. Проверить `meta.dataset` в report JSON.
3. Проследить вызовы `set_meta(...)` в runtime, handler и usecase.
4. **Ожидаемый результат**: один владелец на каждое meta-поле.
5. **Фактический результат**: множественные writer-узлы для одинаковых полей.

---

## 🚫 Почему это проблема?

- Нарушает ответственность между delivery/usecase/report boundary.
- Повышает вероятность регрессий при добавлении новых команд.
- Создаёт шум в отчётах и неявные допущения у потребителей schema.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Сохранить текущую многовладельческую модель
- **Идея**: runtime/handler/usecase продолжают ставить meta по месту.
- **Плюсы**: без миграции.
- **Минусы**: drift ownership остаётся.

### Вариант 2: Явная ownership policy по полям (целевой)
- **Идея**: зафиксировать владельца для каждого meta-поля и убрать fallback dataset.
- **Плюсы**: предсказуемая семантика и отсутствие конфликтов.
- **Минусы**: требуется cleanup вызовов `set_meta(...)` в usecases.

### Вариант 3: Полностью централизовать meta в runtime
- **Идея**: все meta-поля управляются runtime.
- **Плюсы**: один узел записи.
- **Минусы**: runtime начинает знать domain-семантику dataset-aware команд.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [REPORT-DEC-006](./REPORT-DEC-006-report-meta-ownership-policy-and-dataset-boundary.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-010`, `RPT-013`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Проблема зафиксирована |
| 2026-03-02 | Решение принято в REPORT-DEC-006 |
| 2026-03-02 | Проблема закрыта: ownership policy применена, runtime fallback dataset удален |
