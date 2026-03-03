# REPORT-DEC-008: Capability-based `ReportPolicy` и фиксированные profile-presets

> **Статус**: Принято
> **Дата принятия**: 2026-03-02
> **Решает проблему**: REPORT-PROBLEM-008
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

`REPORT-DEC-001` вводит `ReportPolicy` и уровни `minimal/standard/debug`, но не фиксирует capability-контракт каждого уровня. Для стабильной эволюции event-driven report layer требуется формальный policy-contract.

---

## 🎯 Решение

Принять двухуровневую модель `ReportPolicy`:

1. Базовый contract описывается capability-полями.
2. Профили `minimal/standard/debug` — это фиксированные presets над capability-контрактом.
3. Эволюция policy выполняется через добавление новых capability с дефолтами и обновлением matrix/tests.
4. Runtime/usecase не используют ad-hoc правила детализации вне `ReportPolicy`.
5. Effective-решение по хранению skipped items вычисляется как `policy.capabilities.include_skipped_items AND cli_include_skipped` (`cli_include_skipped` после CLI/config resolution); policy задаёт верхнюю границу, CLI только сужает.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/reporting/policy.py`
  - `ReportPolicyCapabilities`
  - `ReportPolicyProfile`
  - `ReportPolicy` + factory methods `minimal()`, `standard()`, `debug()`
- `connector/domain/reporting/policy_matrix.py`
  - profile capability matrix

**Изменения в существующих компонентах**:
- `connector/domain/reporting/assembler.py`
  - принимает только `ReportPolicy` (без inline детализационных флагов).
- `connector/delivery/cli/runtime.py`
  - выбирает профиль policy по конфигу/опциям и передаёт в assembler.

### Интерфейсы

```python
class ReportPolicyProfile(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    DEBUG = "debug"
```

```python
@dataclass(frozen=True)
class ReportPolicyCapabilities:
    include_ok_items: bool
    include_failed_items: bool
    include_skipped_items: bool
    include_payload_masked: bool
    include_upstream_diagnostics: bool
    include_subsystem_metrics: bool
    include_runtime_secondary_as_items: bool
```

```python
@dataclass(frozen=True)
class ReportPolicy:
    profile: ReportPolicyProfile
    capabilities: ReportPolicyCapabilities
```

### Матрица preset-профилей

| Capability | minimal | standard | debug |
|------------|---------|----------|-------|
| include_ok_items | false | false | true |
| include_failed_items | true | true | true |
| include_skipped_items | false | true | true |
| include_payload_masked | false | true | true |
| include_upstream_diagnostics | false | false | true |
| include_subsystem_metrics | false | true | true |
| include_runtime_secondary_as_items | true | true | true |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Ясный и тестируемый policy-контракт.
- ✅ Preset-профили остаются удобными для CLI/runtime.
- ✅ Устраняется ad-hoc детализация на уровне usecase/runtime.
- ✅ Простая эволюция: capability-first, profile-second.

**Недостатки (компромиссы)**:
- ⚠️ Нужно поддерживать matrix в sync с реализацией assembler.
- ⚠️ При добавлении capability требуется обновлять presets и tests.

**Альтернативы, которые отклонили**:
- ❌ **Только profile names без contract**: не даёт стабильных гарантий.
- ❌ **Только флаги без presets**: ухудшает UX и операционную предсказуемость.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/reporting/policy.py` | Новый policy contract и presets |
| `connector/domain/reporting/assembler.py` | Использование capability-based policy |
| `connector/delivery/cli/runtime.py` | Выбор профиля policy |
| `tests/unit/reporting/test_report_policy.py` | Matrix-проверки профилей |
| `tests/integration/reporting/*` | Проверка output по профилям |

### Ключевые методы

- `ReportPolicy.minimal()`
- `ReportPolicy.standard()`
- `ReportPolicy.debug()`
- `ReportAssembler.build(context, policy)`

### Инварианты

1. Каждый profile полностью определяется capability-моделью.
2. Assembler принимает policy только через формальный контракт.
3. Profile-поведение покрыто матричными contract tests.
4. Runtime CLI overrides не могут повышать уровень детализации выше capability-пределов policy.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: presets `minimal/standard/debug` соответствуют фиксированной matrix.
- ✅ Unit: assembler не содержит ad-hoc override profile-правил.
- ✅ Unit: `include_skipped_items` подчиняется формуле `effective = capability AND cli_override`.
- ✅ Integration: одинаковый event-stream даёт ожидаемую разницу output между профилями.
- ✅ Regression: добавление новой capability требует явного обновления presets/tests.

**Проверка в runtime**:
1. Выполнить одну и ту же команду с каждым profile.
2. Сравнить envelope fields по matrix.
3. Убедиться, что runtime/usecase не добавляют profile-specific ветвления вне policy.

**Метрики успеха**:
- Любое изменение детализации отчёта реализуется через `ReportPolicy`, а не через runtime/usecase if-ветки.
- Profiles воспроизводимо дают ожидаемую разницу output.

---

## 📐 Диаграммы

**UML диаграммы** (план):
- [Class Diagram](../../uml/pipeline/report_layer/report_layer_class.puml)
- [Activity Diagram](../../uml/pipeline/report_layer/report_layer_activity.puml)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `debug` профиль не должен ослаблять masking/security правила.

**Риски**:
- ⚠️ Рассинхронизация matrix и реализации assembler.
  - **Митигация**: contract tests + snapshot tests по профилям.
- ⚠️ Неконтролируемое расширение capability без дефолтов.
  - **Митигация**: required update check в тестах на profile completeness.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/domain/reporting/assembler.py` | Высокое | Переход на capability-based policy contract |
| `connector/delivery/cli/runtime.py` | Среднее | Явный выбор policy profile |
| `docs/dev/layers/report/*` | Среднее | Документировать matrix capabilities |
| `tests/reporting/*` | Высокое | Contract tests на presets |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [ADR Index](../INDEX.md) — добавлены `REPORT-PROBLEM-008` и `REPORT-DEC-008`.
- 🔄 Нужно обновить после реализации:
  - `docs/dev/layers/report/report-models.md`
  - `docs/dev/layers/report/report-pipeline.md`

---

## 🔗 Связанные документы

- [REPORT-PROBLEM-008](./REPORT-PROBLEM-008-report-policy-levels-not-formalized.md)
- [REPORT-DEC-001](./REPORT-DEC-001-execution-context-event-driven-report-layer.md)
- [REPORT-DEC-005](./REPORT-DEC-005-runtime-orchestrator-decomposition-and-explicit-handler-contract.md)
- [REPORT-DEC-007](./REPORT-DEC-007-report-schema-v2-typed-context-rowref-nullable-and-import-plan-skipped-reporting.md)
- [Report architecture issues](../../dev/layers/report/report-architecture-issues.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-02 | Решение предложено |
| 2026-03-02 | Решение принято после обсуждения |
