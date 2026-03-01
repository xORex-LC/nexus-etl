# REPORT-PROBLEM-003: Отсутствие инкапсуляции Collector и единого ReportWritePort

> **Статус**: Закрыто
> **Дата создания**: 2026-03-02
> **Затронутые компоненты**: `ReportCollector`, `ApplyReportPresenter`, `run_with_report`, `report_writer`

---

## 📋 Контекст

Report слой развивается в сторону event-driven модели ([REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)) и unified stage processing ([REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)).  
При этом текущий `ReportCollector` остаётся частично открытым для прямой мутации из внешних компонентов.

На практике разные участки кода обновляют отчёт через разные механизмы:

- через API коллектора (`add_item`, `add_op`, `set_context`);
- прямой записью в поля `summary/items/status/context`.

---

## ⚠️ Проблема

В слое отчётности нет жёсткой границы записи (`ReportWritePort`) и не обеспечена инкапсуляция `ReportCollector`.

Следствия:

- инварианты summary/status могут быть нарушены bypass-путём;
- невозможно гарантировать единый lifecycle обновления отчёта;
- сложнее провести безопасную миграцию на event-driven архитектуру без параллельных write-path.

---

## 🔍 Симптомы

- **Симптом 1**: Презентеры и delivery-код могут обходить API коллектора и мутировать поля напрямую.
- **Симптом 2**: Логика подсчёта summary дублируется вне `ReportCollector`.
- **Симптом 3**: `build()` возвращает mutable структуры, что допускает пост-фактум мутацию уже собранного отчёта.
- **Симптом 4**: Нет единого контракта, который можно enforce-ить тестами как write-boundary.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при расширении presenter/runtime логики отчётности.
- **Критичность**: Высокая.
- **Затронуто**: `import-apply`, runtime lifecycle, все команды, использующие `ReportCollector`.

---

## 🧪 Как воспроизвести

1. Добавить новый агрегат в apply-report поток.
2. Реализовать его прямой записью в `collector.summary`/`collector.items`.
3. Сравнить результат с логикой `add_item()`/`_derive_status()`.
4. **Ожидаемый результат**: обновление возможно только через единый write-порт с инвариантами.
5. **Фактический результат**: прямые мутации обходят инварианты и создают расхождения.

---

## 🚫 Почему это проблема?

- Нарушает encapsulation и data abstraction в доменной модели отчёта.
- Повышает риск регрессий при изменении правил статуса/summary.
- Усложняет архитектурную изоляцию report-слоя и целевой refactor path.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Сохранить текущий подход
- **Идея**: Оставить mix API + direct mutations.
- **Плюсы**: Нет дополнительных изменений в краткосрочной перспективе.
- **Минусы**: Рост техдолга и невозможность enforce-инвариантов.

### Вариант 2: Ввести `ReportWritePort` и инкапсуляцию Collector (целевой)
- **Идея**: Все записи в отчёт только через порт; прямые мутации запретить.
- **Плюсы**: Единый контракт записи, стабильные инварианты, чистые границы.
- **Минусы**: Требуется миграция presenter/runtime и дополнительные тесты.

### Вариант 3: Полный мгновенный переход на event-only слой
- **Идея**: Немедленно отключить `ReportCollector` как write-модель.
- **Плюсы**: Быстрый переход к целевой архитектуре.
- **Минусы**: Высокий риск большого одномоментного breaking-change.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-PROBLEM-002](./REPORT-PROBLEM-002-result-processor-duplication-and-boundary-leak.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-003](./REPORT-DEC-003-report-write-port-and-collector-encapsulation.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-005`, `RPT-006`, `RPT-015`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Проблема зафиксирована |
| 2026-03-02 | Решение принято в REPORT-DEC-003 |
| 2026-03-02 | Проблема закрыта: bridge-окно завершено, запись переведена на canonical `IReportSink.emit(...)` |
