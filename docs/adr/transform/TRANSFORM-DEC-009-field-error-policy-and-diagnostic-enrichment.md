# TRANSFORM-DEC-009: Декларативная политика ошибок полей и обогащение диагностики на стадиях трансформации

> **Статус**: Принято
> **Дата принятия**: 2026-02-27
> **Решает проблему**: [TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-stage-diagnostics-no-field-context-and-no-error-policy.md)

---

## 📋 Контекст

При ошибке DSL-операции в стадиях MAP, NORMALIZE и ENRICH в диагностическое событие (`DiagnosticItem`) не попадает ни имя поля, ни проблемное значение. Поведение при ошибке (пропустить / заблокировать / обнулить) задаётся строкой `on_error: "warn"` без валидации и без возможности задать разное поведение для разных полей одной стадии. Стадии MATCH и RESOLVE уже содержат field-контекст, но лишены явной политики. Подробнее — в [TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-stage-diagnostics-no-field-context-and-no-error-policy.md).

---

## 🎯 Решение

1. Ввести `FieldErrorAction` (enum), `FieldErrorPolicy` (dataclass), `FieldErrorOutcome` (dataclass) и `FieldErrorHandler` (service) в **transform-слое** — инкапсулированная cross-cutting логика обработки ошибок полей.
2. `DiagnosticSeverity` не расширяется: severity в политике — только `ERROR` или `WARNING`.
3. Расширить `DiagnosticItem` полем `value`. `DslIssue` не изменяется — он остаётся сырым результатом DSL-движка. `action_taken` **не добавляется в `DiagnosticItem`** — это transform-specific семантика, которая загрязнила бы общую модель, используемую в 11 стадиях. Audit применённого действия — через structlog в stage core при применении action.
4. В YAML-спеках всех стадий (MAP, NORMALIZE, ENRICH) заменить строковый `on_error` на объектную форму `FieldErrorPolicySpec` — с поддержкой stage-level default и per-rule override.
5. Ядра стадий (normalizer_core, mapper_core, enricher_core) после `engine.apply()` делегируют обработку ошибки в `FieldErrorHandler` — stage cores остаются чистыми orchestrator-ами, не реализуют policy-логику сами.
6. `TransformationEngine` остаётся неизменным — он не знает о политиках.
7. Для RESOLVE: `on_unresolved` не меняется структурно; issue обогащается `field` (уже есть) и `value` (значение ссылки до разрешения).
8. Для MATCH: issue уже содержит `field=identity.primary`; добавляем `value` (значение identity-поля).
9. `diagnostic_catalog.py` удаляется; три живых кода (`MATCH_KEY_MISSING`, `TARGET_ID_MISSING`, `USR_ORG_TAB_CONFLICT`) переезжают в `core_catalog.py`; механизм `get_diagnostic_catalog()` вырезается из `DatasetSpec`.

---

## 🏗️ Архитектурное решение

### Новые компоненты

**`connector/domain/transform/field_policy.py`** — политика принадлежит transform-слою, не DSL:

```python
class FieldErrorAction(str, Enum):
    REJECT = "reject"           # запись не проходит дальше
    CONTINUE = "continue"       # логируем, значение остаётся, запись идёт дальше
    NULLIFY = "nullify"         # поле → None, запись идёт дальше
    USE_DEFAULT = "use_default" # поле → fallback, запись идёт дальше

@dataclass(frozen=True)
class FieldErrorPolicy:
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    action: FieldErrorAction = FieldErrorAction.REJECT
    fallback: Any = None        # только для USE_DEFAULT
```

**Почему не в `dsl/`**: DSL-слой применяет операции и сообщает о сырых ошибках выполнения. Решение «что делать с ошибкой» — это поведение стадии трансформации, а не механика DSL-движка.

**`FieldErrorOutcome`** — результат обработки ошибки, возвращаемый handler-ом:

```python
@dataclass(frozen=True)
class FieldErrorOutcome:
    items: list[DiagnosticItem]  # сформированные DiagnosticItem с полным контекстом
    action: FieldErrorAction      # что делать с полем (применяет stage core)
```

**`FieldErrorHandler`** — инкапсулирует cross-cutting логику, не зависит от конкретной стадии:

```python
class FieldErrorHandler:
    def handle(
        self,
        *,
        raw_issues: Iterable[DslIssue],
        field: str,
        original_value: Any,
        policy: FieldErrorPolicy,
        is_sensitive: bool,
        stage: DiagnosticStage,
        record_ref: RowRef | None,
    ) -> FieldErrorOutcome:
        ...
```

- **ОБЯЗАН**: конвертировать `DslIssue[]` + policy context → `DiagnosticItem[]` + action
- **ЗАПРЕЩЕНО**: знать о структуре конкретной row, о конкретных стадиях, применять action к row

### Изменения в существующих компонентах

**`connector/domain/models.py`** — `DiagnosticItem` (только):
```python
@dataclass
class DiagnosticItem:
    ...
    value: Any = None   # NEW: проблемное значение (None для sensitive полей)
    # action_taken НЕ добавляется: DiagnosticItem используется в 11 стадиях (CACHE, APPLY,
    # SINK, EXTRACT, VALIDATE и др.), а "какое действие применено к полю" — специфика
    # field-error-policy и не имеет смысла вне MAP/NORMALIZE/ENRICH.
    # Audit логируется stage core через structlog при применении action.
```

**Почему `value` в `DiagnosticItem` — общее понятие:**
- `value` следует паттерну уже существующего `field: str | None` — null для стадий, где неприменимо; значимый для MAP/NORMALIZE/ENRICH/MATCH/RESOLVE/VALIDATE
- «Какое значение вызвало это событие» — universally useful; «какое действие было применено к полю» — только field-error-policy

**`connector/domain/reporting/models.py`** — `ReportDiagnostic`:
```python
@dataclass(frozen=True)
class ReportDiagnostic:
    severity: str
    stage: DiagnosticStage
    code: str
    field: str | None
    message: str
    value: Any = None       # NEW: общее понятие, первый класс — попадает в JSON-отчёт
    rule: str | None = None
    # action_taken — намеренно отсутствует: это внутренний механизм field-error-policy,
    # не релевантный для SINK/APPLY/MATCH/CACHE событий
```

**Почему `value` — первый класс в `ReportDiagnostic`, а `action_taken` — нет:**
- `value` — общее понятие, полезное для любого диагностического события (MATCH: какое identity-значение не нашлось; RESOLVE: какой link-value не разрешился; NORMALIZE: какое значение сломало ops). Оператор читает отчёт и видит конкретное значение, породившее ошибку.
- `action_taken` — специфичен для field-error-policy: «pipeline обнулил это поле» имеет смысл только в контексте MAP/NORMALIZE/ENRICH. Остальные стадии не имеют этой семантики. Доступен через structlog для аудита/трейсинга, в JSON-отчёт не попадает.
- Использование `details: dict` для `value` — антипаттерн: превращает семантически важное поле в непрозрачный ключ в словаре, ломает контракт отчёта.

**`connector/domain/dsl/issues.py`** — `DslIssue` **не изменяется**:
- Движок создаёт `DslIssue` с `field=None` — он не знает о полях датасета.
- Стадии, которые создают `DslIssue` напрямую (match_core, resolve_core), уже могут устанавливать `field`.
- `action` в `DslIssue` не появляется: это решение стадии, а не результат выполнения операции.

**YAML-схема (Pydantic)** — новый `FieldErrorPolicySpec`, общий для всех стадий:
```python
class FieldErrorPolicySpec(BaseModel):
    severity: Literal["error", "warning"] = "error"   # не "info": нет третьего bucket'а
    action: Literal["reject", "continue", "nullify", "use_default"] = "reject"
    fallback: Any = None

    def to_domain(self) -> FieldErrorPolicy:
        action = FieldErrorAction(self.action)
        severity = DiagnosticSeverity(self.severity)
        # Инвариант: REJECT обязан быть ERROR — иначе запись пройдёт фильтр стадии
        if action == FieldErrorAction.REJECT and severity != DiagnosticSeverity.ERROR:
            raise ValueError(
                "action=reject requires severity=error: "
                "non-error severity means record passes the stage filter"
            )
        return FieldErrorPolicy(severity=severity, action=action, fallback=self.fallback)
```

### Структура `on_error` в YAML

Stage-level default (применяется ко всем полям стадии) + per-rule override:

```yaml
normalize:
  on_error:              # stage-level default
    severity: warning
    action: continue
  rules:
    - field: email
      ops: [- op: trim]
      # нет on_error → наследует stage-level
    - field: organization_id
      ops: [- op: int_if_digits]
      on_error:           # per-field override
        severity: error
        action: reject
    - field: phone
      ops: [- op: trim]
      on_error:
        severity: warning
        action: nullify   # если trim упал — поставить None, продолжить
```

### Алгоритм в ядре стадии (MAP, NORMALIZE, ENRICH)

Stage core — чистый orchestrator: знает поле, ops, разрешает policy. Всю логику формирования диагностики делегирует `FieldErrorHandler`:

```
для каждого rule = {field, ops, on_error?}:
  1. original_value = row[rule.field]
  2. result = engine.apply(original_value, rule.ops)   # DSL: применяет операции

  3. если нет issues → row[rule.field] = result.value; continue

  4. policy = rule.on_error ?? spec.on_error ?? DEFAULT_FIELD_ERROR_POLICY  # resolve policy
  5. outcome = handler.handle(                          # делегируем FieldErrorHandler
         raw_issues=result.issues,
         field=rule.field,
         original_value=original_value,
         policy=policy,
         is_sensitive=rule.field in spec.sensitive_fields,
         stage=...,
         record_ref=record_ref,
     )

  6. errors/warnings += outcome.items   # severity=ERROR → errors, WARNING → warnings

  7. применить outcome.action к строке + залогировать через structlog:
       REJECT:      ничего (severity=ERROR → запись отсеется фильтром стадии)
                    logger.warning("field_error_rejected", field=..., value=..., code=...)
       CONTINUE:    row[rule.field] = original_value
                    logger.warning("field_error_continued", field=..., action="continue", ...)
       NULLIFY:     row[rule.field] = None
                    logger.warning("field_error_nullified", field=..., action="nullify", ...)
       USE_DEFAULT: row[rule.field] = policy.fallback
                    logger.warning("field_error_defaulted", field=..., action="use_default", ...)
```

**Разделение ответственности**:
- `FieldErrorHandler.handle()` — единственное место создания `DiagnosticItem` для field-level ошибок; не знает о структуре row; не знает о конкретных стадиях
- Stage core — применяет action к row; не знает как строятся DiagnosticItem

### Sensitive fields

В YAML каждой стадии объявляется список чувствительных полей. При создании `DiagnosticItem` для таких полей `value=None` — в диагностику попадает только факт ошибки и имя поля, но не значение:

```yaml
normalize:
  sensitive_fields: [password]
  on_error:
    ...
```

### `append_dsl_issue` — роль сужается

`append_dsl_issue` больше не получает параметр `on_error: str` и не читает `issue.action` (которого нет). Для field-level ошибок стадии создают `DiagnosticItem` напрямую (см. алгоритм выше). `append_dsl_issue` остаётся для не-field ошибок: compile-errors, loader-issues и подобного — где field-контекст неприменим.

### MATCH и RESOLVE

**MATCH** (`match_core.py`): уже устанавливает `field=identity.primary`. Добавляем `value` — значение identity-поля на момент ошибки. Политика на уровне стадии (не per-field), stage-level `on_error` в YAML не требуется — поведение матчера жёстко определено логикой идентификации.

**RESOLVE** (`resolve_core.py`): `on_unresolved` остаётся как есть (это semantic action, не error policy). Добавляем в создаваемые `DslIssue` поля: `field=rule.field` (уже есть) и `value=link_value_before_resolution`.

### Удаление `diagnostic_catalog.py`

| Код | Куда переезжает |
|-----|----------------|
| `MATCH_KEY_MISSING` | `core_catalog.py` |
| `TARGET_ID_MISSING` | `core_catalog.py` |
| `USR_ORG_TAB_CONFLICT` | `core_catalog.py` |
| `INVALID_AVATAR_ID`, `INVALID_INT`, `INVALID_EMAIL`, `INVALID_BOOLEAN` | Удаляются (мёртвые, никогда не эмитировались) |

Убирается `get_diagnostic_catalog()` из `DatasetSpec` и вызов `spec.get_diagnostic_catalog()` из `build_catalog()`.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `TransformationEngine` не изменяется — остаётся generic, без знания о полях и политиках
- ✅ `DslIssue` не изменяется — остаётся сырым результатом выполнения операции
- ✅ `FieldErrorHandler` инкапсулирует cross-cutting логику в одном месте — stage cores остаются чистыми orchestrator-ами
- ✅ Инвариант `REJECT → ERROR` валидируется в `to_domain()` — невалидную policy невозможно создать из YAML
- ✅ `DiagnosticSeverity` не расширяется — нет разрыва с текущей pipeline-моделью (errors/warnings)
- ✅ `DiagnosticItem` не загрязняется transform-специфичной семантикой — `action_taken` не добавляется; audit через structlog в stage core
- ✅ `value` в `DiagnosticItem` и `ReportDiagnostic` — общее понятие по паттерну существующего `field: str | None`; null для стадий, где неприменимо
- ✅ Политика полностью декларативна в YAML: per-stage default + per-field override
- ✅ Sensitive fields защищены от утечки значений в логи/отчёты декларативно
- ✅ Удаление `diagnostic_catalog.py` упрощает добавление новых датасетов — нет per-dataset кода ошибок

**Недостатки (компромиссы)**:
- ⚠️ `FieldErrorAction.PENDING` не вводится — RESOLVE сохраняет `on_unresolved` как семантически отдельный механизм (намеренное ограничение объёма)

**Альтернативы, которые отклонили**:
- ❌ **`FieldErrorPolicy` в `dsl/`**: нарушает границы ответственности — DSL не должен знать о поведении стадий при ошибках
- ❌ **`action` в `DslIssue`**: смешивает результат выполнения операции с политическим решением стадии; DslIssue — это «что произошло», не «что делать»
- ❌ **Добавить `field` в `engine.apply()`**: движок получает знание о семантике поля; value и action_taken всё равно не попадают в диагностику — проблема решена лишь частично
- ❌ **Per-dataset коды в `diagnostic_catalog.py`**: не масштабируется, мёртвый код, смешивает dataset-специфику с инфраструктурой диагностик
- ❌ **`on_error: "warn"` string expand**: добавление новых строк (`"nullify"`, `"use_default"`) без enum — хрупко, не валидируется
- ❌ **Cross-cutting логика в каждом stage core**: дублирование паттерна в normalizer/mapper/enricher — три независимые реализации разойдутся в поведении; нет единого места для инвариантов и изменений
- ❌ **`value`/`action_taken` через `details: dict` в `ReportDiagnostic`**: превращает семантически важные поля в непрозрачные ключи словаря; `details` — escape hatch для отладочных данных DSL (op, args, step, error), смешение с семантическими полями ломает контракт
- ❌ **`action_taken` как первый класс в `ReportDiagnostic`**: transform-специфичная семантика ("nullify/reject") не имеет смысла для SINK/APPLY/CACHE/MATCH событий — 90% записей имели бы `null`, создавая ложное ожидание

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/field_policy.py` | Создать: `FieldErrorAction`, `FieldErrorPolicy`, `FieldErrorOutcome`, `FieldErrorHandler` |
| `connector/domain/models.py` | `DiagnosticItem` + `value: Any = None`; `DiagnosticSeverity` — без изменений |
| `connector/domain/dsl/issues.py` | Не изменяется |
| `connector/domain/dsl/diagnostics.py` | Убрать параметр `on_error: str` — он больше не нужен для field-level ошибок |
| `connector/domain/reporting/models.py` | `ReportDiagnostic` + `value: Any = None` |
| `connector/domain/reporting/diagnostics.py` | `_from_item()` — пробросить `item.value` → `ReportDiagnostic.value` |
| `connector/domain/transform/normalize/normalizer_core.py` | Orchestrator: resolve policy → delegate to handler → apply action |
| `connector/domain/transform/mapping/mapper_core.py` | То же |
| `connector/domain/transform/enrich/enricher_core.py` | То же |
| `connector/domain/transform/matcher/match_core.py` | Добавить `value` при создании `DslIssue` |
| `connector/domain/transform/resolver/resolve_core.py` | Добавить `value` при создании `DslIssue` |
| `connector/domain/diagnostics/core_catalog.py` | Добавить 3 кода из `diagnostic_catalog.py` |
| `connector/datasets/employees/diagnostic_catalog.py` | Удалить |
| `connector/datasets/spec.py` | Удалить `get_diagnostic_catalog()` из `DatasetSpec` |
| `connector/domain/diagnostics/catalog.py` | Удалить вызов `spec.get_diagnostic_catalog()` |
| `datasets/employees.normalize.yaml` | `on_error` → объектная форма + `sensitive_fields` |
| `datasets/employees.mapping.yaml` | Добавить `on_error` per-rule где нужно |
| `datasets/employees.enrich.yaml` | `on_error: warn` → объектная форма |

### Инварианты

1. `TransformationEngine.apply()` не изменяется — не знает о политиках и полях.
2. `DslIssue` не изменяется — остаётся сырым результатом выполнения операции (code, message, details, severity, field=None от движка).
3. `FieldErrorPolicy`, `FieldErrorAction`, `FieldErrorOutcome`, `FieldErrorHandler` живут в `connector/domain/transform/` — не в `dsl/`.
4. `FieldErrorHandler` — единственное место создания `DiagnosticItem` для field-level ошибок. Stage cores (normalizer, mapper, enricher) только делегируют в handler и применяют action к row.
5. `DiagnosticSeverity` не расширяется: severity в policy — только ERROR или WARNING.
6. Инвариант: `action=REJECT` требует `severity=ERROR`. Валидируется в `FieldErrorPolicySpec.to_domain()`.
7. Для полей из `sensitive_fields`: `DiagnosticItem.value = None` — значение не попадает в логи/отчёты.
8. `FieldErrorPolicy` всегда разрешается: rule-level → stage-level → DEFAULT (REJECT, ERROR).
9. `action_taken` **не добавляется в `DiagnosticItem`**: `DiagnosticItem` используется в 11 стадиях (CACHE, APPLY, SINK, …), «какое действие применено к полю» бессмысленно вне MAP/NORMALIZE/ENRICH. Audit применённого действия — через structlog в stage core (шаг 7 алгоритма).
10. `value` в `DiagnosticItem` и `ReportDiagnostic` — общее понятие, аналогичное существующему `field: str | None`. Null для стадий, где неприменимо. Пробрасывается через `_from_item()`.

---

## 🧪 Валидация решения

**Тесты**:
- `test_normalizer_field_error_with_policy_reject()` — field + value в DiagnosticItem, запись блокируется
- `test_normalizer_field_error_with_policy_nullify()` — поле → None, запись проходит; в DiagnosticItem field/value заполнены
- `test_normalizer_field_error_with_policy_use_default()` — поле → fallback, запись проходит; в DiagnosticItem field/value заполнены
- `test_normalizer_sensitive_field_no_value_in_diagnostic()` — value=None для sensitive полей
- `test_mapper_field_context_in_diagnostic()` — field попадает в DiagnosticItem из MAP стадии
- `test_enricher_policy_override_per_generator()` — per-generator policy работает
- `test_resolve_issue_has_field_and_value()` — RESOLVE: field и value обогащены
- `test_match_issue_has_value()` — MATCH: value identity-поля в диагностике

**Метрики успеха**:
- `DiagnosticItem.field is not None` для всех ошибок MAP/NORMALIZE/ENRICH (где поле известно)
- `DiagnosticItem.value is not None` для не-sensitive полей при ошибке
- `diagnostic_catalog.py` удалён, тесты проходят без него

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `FieldErrorAction.PENDING` не реализован — RESOLVE продолжает использовать `on_unresolved` как самостоятельный механизм
- `DiagnosticItem.occurred_at` (timestamp) не вводится в данном решении — отложено

**Риски**:
- ⚠️ Изменение `DiagnosticItem` (новые поля) может потребовать обновления сериализаторов/репортеров
  - **Митигация**: поля опциональные (`= None`), backward-совместимы
- ⚠️ `FieldErrorPolicy.fallback` типизирован как `Any` — некорректный тип для поля может пройти валидацию YAML
  - **Митигация**: при компиляции стадии Pydantic валидирует структуру; runtime-ошибка при `USE_DEFAULT` с некорректным значением создаст `DslIssue` с кодом `DSL_OP_FAILED`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `DiagnosticItem` (domain model) | Новое поле | `value: Any = None` — опциональное; `action_taken` не добавляется |
| `DiagnosticSeverity` | Без изменений | ERROR и WARNING — достаточно; INFO не вводится |
| `DslIssue` | Без изменений | Остаётся сырым результатом DSL-движка |
| `ErrorCatalog` / `build_catalog()` | Удаление зависимости | Убрать `get_diagnostic_catalog()` |
| `DatasetSpec` | Удаление метода | Убрать `get_diagnostic_catalog()` |
| `ReportDiagnostic` (reporting model) | Новое поле | `value: Any = None` — первый класс, общее понятие |
| `_from_item()` (reporting/diagnostics.py) | Маппинг | Добавить `value=item.value` |
| JSON-отчёт | Расширение контракта | Новое поле `value` в каждом diagnostic-объекте |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-stage-diagnostics-no-field-context-and-no-error-policy.md) — решаемая проблема
- [DSL-DEC-001](../dsl/DSL-DEC-001-strict-compile-validation-and-diagnostics-hardening.md) — предшествующее усиление DSL-диагностик
- [DSL-DEC-002](../dsl/DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — модульность DSL Core
- [TRANSFORM-PROBLEM-009](./TRANSFORM-PROBLEM-009-sink-validation-cross-cutting-in-stage-cores.md) — смежная cross-cutting диагностика

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-27 | Решение принято после анализа `diagnostic_catalog.py` и field-context gap |
| 2026-02-27 | Скорректировано: `FieldErrorPolicy` перенесена из `dsl/` в `transform/`; `DslIssue` не изменяется; стадии строят `DiagnosticItem` напрямую |
| 2026-02-27 | Скорректировано: `value` — первый класс в `ReportDiagnostic`; `action_taken` — только `DiagnosticItem` + structlog; `details: dict` как носитель семантики отклонён |
| 2026-02-27 | Скорректировано: введены `FieldErrorOutcome` и `FieldErrorHandler`; убран `INFO` из `DiagnosticSeverity`; инвариант `REJECT→ERROR` валидируется в `to_domain()`; stage cores — orchestrators, не реализуют policy |
| 2026-02-27 | Скорректировано: `action_taken` убран из `DiagnosticItem` (transform-specific, 11 стадий); audit через structlog в stage core; `value` подтверждено как общее понятие (паттерн `field: str | None`) |
