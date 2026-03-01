# REPORT-PROBLEM-002: Дублирование ResultProcessor и утечка report-адаптера в transform/core

> **Статус**: Закрыто
> **Дата создания**: 2026-03-01
> **Затронутые компоненты**: `TransformResultProcessor`, `PlanningResultProcessor`, `MatchUseCase`, `ResolveUseCase`, `ReportCollector`

---

## 📋 Контекст

Исторически адаптация row-level результатов к отчёту была реализована в `connector/domain/transform/core/result_processor.py`.  
На этом пути сформировались два близких по алгоритму процессора:

- `TransformResultProcessor` для `normalize/mapping/enrich`;
- `PlanningResultProcessor` для `match/resolve` с `meta_builder` и `should_skip`.

По мере роста требований к отчётности (stage-scoped diagnostics, masking, runtime consistency) код процессоров стал зоной пересечения нескольких ролей.

---

## ⚠️ Проблема

Текущая реализация содержит дублирование и смешение ответственности:

- duplicated `process()`-логика в двух классах;
- в одном месте смешаны подсчёт статистики, фильтрация diagnostics, masking payload, запись в `ReportCollector` и формирование `CommandResult`;
- модуль transform/core зависит от report semantics, что размывает responsibility boundaries между слоями.

Дополнительно различия сценариев `match` и `resolve` приводят к трудно сопоставимым stage-метрикам.

---

## 🔍 Симптомы

- **Симптом 1**: Любое изменение алгоритма `process()` требует синхронных правок в двух классах.
- **Симптом 2**: Поведение управляется магическими строками `context_key/ok_label/failed_label`.
- **Симптом 3**: `match` и `resolve` по-разному обрабатывают upstream-поток, из-за чего отчётные метрики несопоставимы.
- **Симптом 4**: Логика формирования `CommandResult` живёт рядом с report-адаптацией, что усложняет границы ответственности.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при эволюции report-правил и stage-метрик.
- **Критичность**: Высокая.
- **Затронуто**: Команды `normalize`, `mapping`, `enrich`, `match`, `resolve` и их JSON-отчёты.

---

## 🧪 Как воспроизвести

1. Добавить новое правило формирования `meta` или masking payload в процессор результатов.
2. Внести изменение в `TransformResultProcessor.process()`.
3. Повторить аналогичное изменение в `PlanningResultProcessor.process()`.
4. Сравнить метрики `status/summary` для сценариев `match` и `resolve` при upstream-ошибках.
5. **Ожидаемый результат**: одна точка изменения и консистентная stage-политика.
6. **Фактический результат**: двойные правки, риск расхождения алгоритмов и неоднородные stage-метрики.

---

## 🚫 Почему это проблема?

- Нарушения SRP/OCP/DRY затрудняют безопасный рефакторинг.
- Размыты границы layer ownership: transform/core фактически содержит report-адаптер.
- Усложняется переход к event-driven Execution Context из [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md).
- Повышается вероятность регрессий при расширении правил отчётности.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Оставить наследование `PlanningResultProcessor(TransformResultProcessor)`
- **Идея**: Продолжить поддержку двух процессоров с точечными фикcами.
- **Плюсы**: Минимальные изменения в коде.
- **Минусы**: Сохраняет дублирование и не решает проблему ownership границ.

### Вариант 2: Unified core через композицию + стратегии (целевой)
- **Идея**: Ввести единый canonical processor и выделить стратегии `should_skip/build_meta/build_payload`, статистику и masking в отдельные компоненты.
- **Плюсы**: Устраняет дублирование, стабилизирует ответственность, упрощает тестирование.
- **Минусы**: Требует миграционного окна и обновления контрактов usecase/report.

### Вариант 3: Полная централизация в runtime
- **Идея**: Перенести правила обработки result/status полностью в `delivery/cli/runtime.py`.
- **Плюсы**: Один центральный оркестратор.
- **Минусы**: Усиливает god-module runtime, смешивает бизнес-правила стадий с delivery orchestration.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-008`, `RPT-009`, `RPT-012`, `RPT-014`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-01 | Проблема зафиксирована |
| 2026-03-01 | Решение принято в REPORT-DEC-002 |
| 2026-03-02 | Проблема закрыта: legacy alias удалены, canonical StageResultReporter остался единственным путем |
