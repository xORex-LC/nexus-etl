# REPORT-PROBLEM-007: Report schema contract gap (v2), typed context и skipped-reporting

> **Статус**: Закрыто
> **Дата создания**: 2026-03-02
> **Затронутые компоненты**: `ReportMeta`, `ReportSummary`, `ReportItem`, `RowRef`, `import_plan`, `ReportCollector`

---

## 📋 Контекст

Текущая report schema и execution path содержат несколько семантических разрывов:

- `items_truncated` выставляется только для `OK/FAILED`;
- `context`/`summary.ops` опираются на магические строки;
- `RowRef.line_no` принудительно нормализуется `None -> 0` в отдельных путях;
- CLI опция `--report-include-skipped` объявлена, но не wired в `import-plan` execution path.

Новые решения report layer требуют формализованного schema contract следующей версии.

---

## ⚠️ Проблема

Отсутствует единый, типизированный и явно версионированный schema-contract для report v2.

Следствия:
- неконсистентность item/status semantics;
- непрозрачность для downstream consumers;
- расхождения между CLI-contract и реальным поведением.

---

## 🔍 Симптомы

- **Симптом 1**: `items_truncated` не отражает усечение для статусов вне `OK/FAILED`.
- **Симптом 2**: `context` и `ops` расширяются ad-hoc строковыми ключами.
- **Симптом 3**: `line_no=None` теряется при нормализации до `0`.
- **Симптом 4**: `--report-include-skipped` не влияет на отчёт import-plan.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при расширении report schema и CLI contract.
- **Критичность**: Высокая.
- **Затронуто**: Report consumers, CLI пользователи, import-plan/import-apply сценарии.

---

## 🧪 Как воспроизвести

1. Выполнить `import plan --report-include-skipped` и проверить report items.
2. Сгенерировать отчёт с усечением items для status вне `OK/FAILED`.
3. Проверить `line_no` в apply-представлении при `RecordRef.line_no=None`.
4. **Ожидаемый результат**: контракт v2 явно фиксирует status/summary/context semantics.
5. **Фактический результат**: поведение фрагментировано и частично не wired.

---

## 🚫 Почему это проблема?

- Нарушает API consistency между CLI и report artifacts.
- Повышает риск ошибок при интеграции и аналитике.
- Усложняет миграцию к event-driven report architecture.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Локальные фиксы без schema versioning
- **Идея**: точечно исправлять поведение без явной v2 схемы.
- **Плюсы**: быстрое внедрение.
- **Минусы**: дрейф контрактов продолжится.

### Вариант 2: Ввести report schema v2 (целевой)
- **Идея**: typed schema, version marker, явная skipped semantics.
- **Плюсы**: контрактная стабильность и предсказуемая эволюция.
- **Минусы**: breaking change для consumers.

### Вариант 3: Отложить до полного event-driven перехода
- **Идея**: не менять текущую схему до финального rework.
- **Плюсы**: меньше изменений сейчас.
- **Минусы**: текущие API несоответствия остаются.

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-001](./REPORT-PROBLEM-001-report-layer-mixed-responsibilities-and-missing-execution-context.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-007](./REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md) (`RPT-004`, `RPT-014`, `RPT-016`, `RPT-017`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Проблема зафиксирована |
| 2026-03-02 | Решение принято в REPORT-DEC-007 |
| 2026-03-02 | Проблема закрыта: schema v2 внедрена, skipped-contract и typed context реализованы |
