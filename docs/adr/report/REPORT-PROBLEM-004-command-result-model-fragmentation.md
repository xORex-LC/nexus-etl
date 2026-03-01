# REPORT-PROBLEM-004: Фрагментация модели CommandResult между domain и delivery

> **Статус**: Закрыто
> **Дата создания**: 2026-03-02
> **Затронутые компоненты**: `domain.diagnostics.CommandResult`, `delivery.cli.CommandResult`, `run_with_report`, `runtime result mapping`

---

## 📋 Контекст

В runtime pipeline одновременно поддерживаются разные формы результата команды:

- `DomainCommandResult` (domain/diagnostics);
- `CliCommandResult` (delivery/cli);
- `int` exit-code.

Это усложняет mapping в отчёт и вынуждает `runtime.py` поддерживать несколько веток преобразования.

---

## ⚠️ Проблема

Нет одного канонического контракта результата команды.  
Из-за этого report-layer и runtime orchestration вынуждены содержать compatibility-ветки, а семантика статусов/диагностик становится менее прозрачной.

---

## 🔍 Симптомы

- **Симптом 1**: В runtime есть отдельные пути для `DomainCommandResult`, `CliCommandResult` и `int`.
- **Симптом 2**: Возникают synthetic diagnostics для выравнивания поведения между моделями.
- **Симптом 3**: Exit/report semantics труднее удерживать консистентными при расширении команд.
- **Симптом 4**: Usecase-level коды и delivery-level статусы частично дублируют смысл друг друга.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при изменении обработки результатов в runtime и report.
- **Критичность**: Высокая.
- **Затронуто**: Все CLI команды и runtime lifecycle (`init/handler/shutdown/finalize`).

---

## 🧪 Как воспроизвести

1. Ввести новую команду/ветку, возвращающую `CliCommandResult`.
2. Добавить альтернативную ветку с `DomainCommandResult`.
3. Сравнить, как эти ветки материализуются в report items/diagnostics и exit code.
4. **Ожидаемый результат**: единая result-модель и единый mapping path.
5. **Фактический результат**: несколько веток преобразования и compatibility-политики.

---

## 🚫 Почему это проблема?

- Нарушает data abstraction и повышает когнитивную сложность runtime orchestration.
- Увеличивает риск расхождения между report status, diagnostics и exit-code semantics.
- Тормозит декомпозицию `runtime.py` и усложняет migration к чистой модели отчётности.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Сохранить dual-model постоянно
- **Идея**: Продолжать поддерживать обе модели без дедлайна на консолидацию.
- **Плюсы**: Нулевой миграционный риск сегодня.
- **Минусы**: Постоянный техдолг в runtime/report mapping.

### Вариант 2: Канонический domain result + legacy adapter (целевой)
- **Идея**: Принять `DomainCommandResult` как единственный canonical контракт; legacy формы адаптировать на boundary.
- **Плюсы**: Прозрачная семантика, один mapping path, проще тестировать.
- **Минусы**: Требуется этапная миграция delivery handlers.

### Вариант 3: Перейти на `int` как единственный контракт
- **Идея**: Все команды возвращают только exit code, а runtime сам строит диагностику.
- **Плюсы**: Простая сигнатура.
- **Минусы**: Потеря богатой доменной диагностики и усиление runtime coupling.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-PROBLEM-002](./REPORT-PROBLEM-002-result-processor-duplication-and-boundary-leak.md)
- [REPORT-DEC-002](./REPORT-DEC-002-unified-stage-result-reporter-and-result-policy.md)
- [REPORT-DEC-004](./REPORT-DEC-004-canonical-command-result-and-runtime-boundary-adapter.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-001`, `RPT-003`, `RPT-012`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Проблема зафиксирована |
| 2026-03-02 | Решение принято в REPORT-DEC-004 |
| 2026-03-02 | Проблема закрыта: compatibility path `CliCommandResult/int` удален, runtime работает на `DomainCommandResult` |
