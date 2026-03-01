# REPORT-PROBLEM-005: Перегруженный runtime orchestrator и неявный контракт command handlers

> **Статус**: Открыта
> **Дата создания**: 2026-03-02
> **Затронутые компоненты**: `connector/delivery/cli/runtime.py`, command handlers, `CliCommandResult`, `DomainCommandResult`

---

## 📋 Контекст

После фиксации базовых решений по report layer (`REPORT-DEC-001..004`) runtime продолжает совмещать несколько ролей в одном модуле:

- lifecycle orchestration;
- dispatch handlers по сигнатуре через reflection;
- result normalization;
- result-to-report mapping;
- finalization/shutdown policy.

Одновременно runtime поддерживает переходный compatibility-path для нескольких моделей результата команды.

---

## ⚠️ Проблема

`runtime.py` остаётся перегруженным orchestration-модулем и держит неявный контракт handlers (`handler(ctx, opts)` и `handler(ctx, opts, report)`).

Это нарушает границы ответственности delivery-слоя и затрудняет безопасный рефакторинг report pipeline.

---

## 🔍 Симптомы

- **Симптом 1**: `_call_handler()` использует `inspect.signature()` для выбора способа вызова handler.
- **Симптом 2**: runtime содержит широкий branching по типам результата (`DomainCommandResult`, `CliCommandResult`, `int`).
- **Симптом 3**: изменения report/exit semantics требуют правок в одном крупном модуле с высокой связностью.
- **Симптом 4**: сложно обеспечить единый контракт на уровне тестов и архитектурных guardrails.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при изменениях delivery runtime и report mapping.
- **Критичность**: Высокая.
- **Затронуто**: Все CLI команды, lifecycle paths `init/handler/shutdown/finalize`.

---

## 🧪 Как воспроизвести

1. Добавить новую команду с 2-аргументным handler (`ctx, opts`).
2. Добавить вторую команду с 3-аргументным handler (`ctx, opts, report`).
3. Изменить policy runtime result mapping.
4. **Ожидаемый результат**: явный единый handler interface и локализованные изменения.
5. **Фактический результат**: runtime вынужден поддерживать reflection-dispatch и смешанные compatibility ветки.

---

## 🚫 Почему это проблема?

- Повышает риск регрессий при эволюции runtime/report boundaries.
- Поддерживает неявный API-контракт handlers.
- Задерживает реализацию `REPORT-DEC-004` до полноценного canonical path.
- Ухудшает тестируемость и декомпозицию delivery-слоя.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Сохранить текущий runtime orchestration
- **Идея**: оставить reflection-dispatch и mixed result support в `runtime.py`.
- **Плюсы**: минимальные изменения сейчас.
- **Минусы**: закрепление архитектурного долга.

### Вариант 2: Явный handler contract + декомпозиция runtime (целевой)
- **Идея**: убрать `inspect.signature`, разделить orchestration/invocation/mapping/finalization.
- **Плюсы**: чистые границы и управляемая миграция compatibility-path.
- **Минусы**: требует этапной миграции handlers и runtime tests.

### Вариант 3: Перенести mapping целиком в handlers
- **Идея**: runtime только вызывает handler и завершает процесс.
- **Плюсы**: более тонкий runtime.
- **Минусы**: дублирование mapping policy между командами.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-PROBLEM-004](./REPORT-PROBLEM-004-command-result-model-fragmentation.md)
- [REPORT-DEC-004](./REPORT-DEC-004-canonical-command-result-and-runtime-boundary-adapter.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-007`, `RPT-018`, `RPT-012`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Проблема зафиксирована |
| 2026-03-02 | Решение принято в REPORT-DEC-005 |
