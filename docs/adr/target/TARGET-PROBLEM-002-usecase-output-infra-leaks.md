# TARGET-PROBLEM-002: Use-case Apply загрязнён output/infra деталями и размывает границы ответственности

> **Статус**: Открыта
> **Дата создания**: 2026-02-13
> **Затронутые компоненты**: `connector/usecases/import_apply_service.py`, `connector/domain/report/report_collector.py`, `connector/infra/logging/setup.py`, `connector/delivery/commands/import_apply.py`

---

## 📋 Контекст

В проекте уже сформирована корректная high-level структура: доменные порты для исполнения запросов (`RequestExecutorProtocol`) и чтения target (`TargetPagedReaderProtocol`), а также use-case сценарий применения плана (apply), который должен оставаться target-agnostic.

Однако `ImportApplyService` со временем вобрал в себя дополнительные обязанности, не относящиеся к orchestration сценарию:
- непосредственная работа с отчётом (report) и форматирование контекста/summary;
- прямые вызовы инфраструктурного логирования (`logEvent`);
- зависимость от деталей runtime/инфра-реализации (интроспекция ретраев/клиента через executor).

Это становится особенно заметно на фоне текущей инициативы “почистить load-слой” (TargetRuntime/target-slice): даже если delivery перестанет знать Ankey-специфику, use-case всё ещё будет тянуть инфраструктурные детали и “presentation concerns”.

---

## ⚠️ Проблема

`ImportApplyService` смешивает несколько уровней ответственности:

- **Use-case orchestration** (правильно): пройти план, вызвать адаптер, исполнить запрос через порт, собрать результат сценария.
- **Presentation/output** (лишнее для use-case): писать в `ReportCollector`, наполнять meta/context/summary и управлять детализацией/лимитами вывода.
- **Infrastructure details** (недопустимо для use-case): вызывать `connector.infra.*` (логирование) и опираться на детали конкретной реализации executor/клиента (например, статистика ретраев).

В итоге размывается граница “use-case ↔ delivery/output ↔ infra”, что усложняет рефакторинг target-slice, переиспользование use-case вне CLI и тестирование.

---

## 🔍 Симптомы

- Use-case нельзя безопасно переиспользовать в другом runtime (worker/scheduler/HTTP), потому что он “знает” про отчёт/логирование/контекст CLI.
- Изменение структуры отчёта или правил вывода тянет изменения в use-case (эффект “presentation leaks into application”).
- Хрупкие тесты: приходится патчить/подменять не только порты (`executor`, `secrets`, `runtime_port`), но и поведение отчёта/логирования.
- При очистке load-слоя (TargetRuntime) часть infra-зависимостей всё равно останется внутри use-case (например, runtime stats).

---

## 📊 Масштаб проблемы

- **Частота**: Всегда (каждый запуск `apply` проходит через `ImportApplyService`)
- **Критичность**: Средняя → Высокая (мешает дальнейшему выносу target-специфики в infra и снижает тестируемость)
- **Затронуто**:
  - Use-case: `ImportApplyService`
  - Delivery: команда `import_apply` (смешанный ownership отчёта)
  - Infra: logging/event helpers, runtime stats
  - Tests: unit/integration/e2e вокруг apply и отчётов

---

## 🧪 Как воспроизвести

1. Открыть `connector/usecases/import_apply_service.py`.
2. Найти прямые обращения к инфраструктуре (например, импорт/вызов `connector.infra.*`).
3. Найти места, где use-case формирует output (работает с `report`, summary/context) вместо возврата “чистого” результата сценария.
4. **Ожидаемый результат**:  
   Use-case реализует orchestration сценария и возвращает структурированный результат; output/логирование/контекст — ответственность delivery или output-port адаптера.
5. **Фактический результат**:  
   Use-case пишет в report, вызывает infra logging и опирается на runtime детали executor/клиента.

Пример быстрых проверок:

```bash
# Ищем infra-утечки и плотную работу с отчётом внутри use-case
rg -n "connector\.infra\.|logEvent|report\.|set_meta|set_context|add_item|add_op" connector/usecases/import_apply_service.py

# Проверяем, что часть output ответственности также есть в delivery
rg -n "report\.|set_meta|set_context" connector/delivery/commands/import_apply.py
```

---

## 🚫 Почему это проблема?

- Нарушает смысл Clean/Hex: use-case становится зависим от внешних механизмов (логирование/отчёты/детали runtime), а не только от портов.
- Усложняет внедрение TargetRuntime/target-slice: даже при “чистом wiring” delivery ↔ infra, use-case остаётся источником утечек.
- Снижает тестируемость: тесты вынуждены учитывать детали presentation/output и инфраструктурных сайд-эффектов.
- Увеличивает стоимость изменений: любые изменения формата отчёта/логирования каскадно затрагивают application logic.
- Размывает ownership: неясно, кто отвечает за meta/context/summary (delivery или use-case), что ведёт к дублированию и конфликтам.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Оставить report в use-case, но убрать infra-утечки (минимальная очистка)
- **Идея**:
  - Use-case остаётся владельцем детализации `ReportCollector` (items/ops),
  - но удаляются прямые `connector.infra.*` импорты и runtime-интроспекция executor/клиента.
- **Плюсы**:
  - минимальные изменения,
  - сохраняется текущая архитектура отчёта.
- **Минусы**:
  - use-case всё равно смешивает orchestration и output,
  - ограниченная переиспользуемость вне CLI.

### Вариант 2: Use-case возвращает “ApplyResult”, а delivery собирает report (разделение output ответственности)
- **Идея**:
  - Use-case возвращает структурированный результат сценария (counts + diagnostics summary + item outcomes),
  - delivery/handler переводит это в `ReportCollector`.
- **Плюсы**:
  - use-case становится “чистым” application logic,
  - проще тестировать и переиспользовать.
- **Минусы**:
  - delivery станет толще (сборка отчёта),
  - нужно аккуратно решить лимиты детализации (items_limit).

### Вариант 3: Ввести маленький OutputPort/Observer для apply (компромисс)
- **Идея**:
  - Use-case пишет события сценария в интерфейс `ApplyOutputPort`,
  - реализация в delivery пишет в `ReportCollector`, тесты используют `NullOutput`.
- **Плюсы**:
  - разделение ответственности без “толстого delivery”,
  - расширяемость (можно писать в report/metrics/tracing).
- **Минусы**:
  - добавляется ещё один интерфейс/адаптер (но локально и минимально).

---

## 🔗 Связанные документы

- [ADR INDEX](../INDEX.md) — реестр ADR и соглашения по именованию
- [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md) — проблема target wiring в delivery
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) — решение по TargetRuntime/target-slice

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Зафиксирована проблема: use-case apply смешивает orchestration, output и infra детали |
| 2026-02-13 | Принято выделить отдельную PROBLEM для последующего DECISION (граница use-case ↔ output/infra) |
