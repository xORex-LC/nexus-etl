# TRANSFORM-DEC-009: Декларативный DatasetSpec — YAML-driven dataset plugins

> **Статус**: Принято
> **Дата принятия**: 2026-03-09
> **Решает проблему**: [TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-hardcoded-dataset-spec-blocks-extensibility.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`EmployeesSpec` хардкодит dataset-specific конфигурацию (report adapter, apply adapter, diagnostic catalog, payload builder) в Python, хотя эти данные декларативны по природе. Добавление нового датасета невозможно без написания Python-кода. При этом `employees.sink.yaml` уже содержит все field mappings, дублируемые в `build_user_upsert_payload` ([TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-hardcoded-dataset-spec-blocks-extensibility.md)).

Параллельно, [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md) зафиксировал Phase 2: замену typed `build_*_spec()` методов на generic accessor `build_spec_for(stage_type)`. Данное решение реализует обе фазы одновременно.

---

## 🎯 Решение

**Dataset DSL + Generic YamlDatasetSpec + SinkSpec-driven payload builder + auto-discovery:**

1. Расширить `datasets/registry.yml` секциями `report:`, `apply:`, `diagnostics:` per dataset
2. Создать доменный модуль `connector/domain/dataset_dsl/` с Pydantic-моделями и компиляторами
3. Реализовать `SinkDrivenPayloadBuilder` — generic payload builder из SinkSpec field metadata
4. Создать `YamlDatasetSpec` — generic DatasetSpec implementation из YAML-конфигурации
5. Реализовать Phase 2 из DEC-005: `build_spec_for(stage_type)` generic accessor
6. Auto-discovery датасетов из `registry.yml` вместо хардкодированного `_registry`
7. Escape hatch: опциональный `spec_class:` в registry.yml для кастомных Python-реализаций

---

## 🏗️ Архитектурное решение

### Новые компоненты

**Модуль `connector/domain/dataset_dsl/`:**
- `specs.py` — Pydantic-модели (`ReportAdapterSpec`, `ApplyAdapterSpec`, `DiagnosticEntrySpec`, `DatasetDslSpec`)
- `loader.py` — `load_dataset_dsl_spec(dataset)` из registry.yml
- `coercions.py` — type coercion функции (`to_bool`, `to_int_or_none`)
- `payload_compiler.py` — `SinkDrivenPayloadBuilder` (callable, из SinkSpec field metadata)
- `params_compiler.py` — generic params builders (`build_target_id_params`, `resolve_params_builder`)
- `catalog_compiler.py` — `compile_diagnostic_catalog` (DSL entries → ErrorCatalog)

**`connector/datasets/yaml_spec.py`:**
- `YamlDatasetSpec` — generic DatasetSpec из YAML

### Расширение registry.yml

```yaml
datasets:
  employees:
    source: employees.source.yaml
    # ... existing stage refs ...
    report:
      identity_label: match_key
      conflict_code: MATCH_CONFLICT
      conflict_field: matchKey
    apply:
      operation_alias: users.upsert
      payload:
        source: sink
        defaults: { avatarId: null }
        conditional_fields: [password]
      params:
        mode: target_id
    diagnostics:
      - code: INVALID_AVATAR_ID
        system_code: DATA_INVALID
        severity: ERROR
        message: "avatarId must be empty or null"
      # ...
```

### SinkSpec-driven payload building

`SinkDrivenPayloadBuilder` заменяет `build_user_upsert_payload`, используя метаданные из SinkSpec:

| SinkFieldSpec | Использование |
|---|---|
| `name` | Source key (snake_case) |
| `target` | Payload key (camelCase mapping) |
| `type` | Dispatch coercion: `"bool"` → `to_bool`, `"int"` → `to_int_or_none` |
| `required` | Validate non-empty (кроме conditional_fields) |
| `nullable` | Allow None |

Plus: `defaults` (constant fields), `conditional_fields` (include only when non-empty).

### DatasetSpec Protocol (Phase 2)

```python
class DatasetSpec(Protocol):
    dataset_name: str

    def build_spec_for(self, stage_type: str) -> object: ...
    def build_record_source(self, csv_has_header: bool) -> Iterable[SourceRecord]: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapterProtocol: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
```

### Auto-discovery + escape hatch

```python
def _build_registry() -> dict[str, callable]:
    for name, entry in registry["datasets"].items():
        if entry.get("spec_class"):
            result[name] = _import_spec_factory(entry["spec_class"])
        else:
            result[name] = partial(_make_yaml_spec, name)
```

### Поток данных

```
registry.yml
  ├─ stage refs → load_*_spec_for_dataset() → stage specs (уже работает)
  ├─ report: → ReportAdapterSpec → ReportAdapter
  ├─ apply: → ApplyAdapterSpec → OperationApplyAdapter
  │    └─ payload.source=sink → SinkSpec (employees.sink.yaml) → SinkDrivenPayloadBuilder
  └─ diagnostics: → DiagnosticEntrySpec[] → ErrorCatalog
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Zero Python для нового датасета — только YAML-конфигурация
- ✅ Устранение дублирования: payload builder использует SinkSpec field metadata
- ✅ Единый source of truth: `registry.yml` + stage YAML файлы
- ✅ Phase 2 DEC-005 реализуется: OCP полностью закрыт для DatasetSpec
- ✅ Escape hatch сохраняет гибкость для edge cases

**Недостатки (компромиссы)**:
- ⚠️ `build_spec_for()` возвращает `object` — потеря статической типизации на уровне Protocol. Приемлемо: `StageDescriptor.engine_factory` знает ожидаемый тип
- ⚠️ Расширение registry.yml увеличивает его объём. Приемлемо: всё в одном месте, консистентно с `build_options`

**Альтернативы, которые отклонили**:
- ❌ **Отдельные `{dataset}.dataset.yaml` файлы**: Лишний уровень indirection, registry.yml уже играет роль центрального реестра
- ❌ **YAML-only без escape hatch**: Недостаточно гибко для сложной кастомной логики
- ❌ **Только Phase 1 (typed методы)**: Раз заменяем EmployeesSpec — логично сразу перейти на generic accessor

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/dataset_dsl/specs.py` | Новый: Pydantic-модели DatasetDslSpec |
| `connector/domain/dataset_dsl/loader.py` | Новый: загрузчик из registry.yml |
| `connector/domain/dataset_dsl/coercions.py` | Новый: type coercion (из payloads/users.py) |
| `connector/domain/dataset_dsl/payload_compiler.py` | Новый: SinkDrivenPayloadBuilder |
| `connector/domain/dataset_dsl/params_compiler.py` | Новый: generic params builders |
| `connector/domain/dataset_dsl/catalog_compiler.py` | Новый: DSL → ErrorCatalog |
| `connector/datasets/yaml_spec.py` | Новый: YamlDatasetSpec |
| `connector/datasets/spec.py` | Изменён: Phase 2 Protocol |
| `connector/datasets/registry.py` | Изменён: auto-discovery |
| `connector/delivery/cli/containers.py` | Изменён: build_spec_for() |
| `datasets/registry.yml` | Расширен: report/apply/diagnostics |
| `connector/datasets/employees/spec.py` | Удалён |
| `connector/datasets/employees/diagnostic_catalog.py` | Удалён |

### Инварианты

1. `build_spec_for(stage_type)` не делает I/O — возвращает объект из уже загруженного конфига
2. `UnsupportedStageError` (не `KeyError`) для неизвестных стадий
3. `SinkDrivenPayloadBuilder` побитово идентичен `build_user_upsert_payload` для тех же входных данных
4. Auto-discovery не ломает существующие `get_spec()` / `list_specs()` контракты

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Equivalence test: `SinkDrivenPayloadBuilder` vs `build_user_upsert_payload` — идентичный output
- ✅ `build_spec_for("map")` → `MappingSpec`, `build_spec_for("unknown")` → `UnsupportedStageError`
- ✅ Auto-discovery: `get_spec("employees")` → `YamlDatasetSpec`
- ✅ Pydantic validation: корректная валидация DatasetDslSpec из YAML

**Метрики успеха**:
- Добавление нового датасета: 0 строк Python-кода, только YAML
- Все 305+ существующих тестов проходят без изменений

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `SinkDrivenPayloadBuilder` поддерживает только coercion rules из SinkFieldSpec.type (`string`, `bool`, `int`, `float`). Для сложных трансформаций — escape hatch через `spec_class:`
- `conditional_fields` и `defaults` должны быть явно указаны в registry.yml

**Риски**:
- ⚠️ Payload behavioral equivalence — coercion edge cases могут отличаться → Митигация: equivalence test
- ⚠️ Phase 2 blast radius (PipelineContainer + command handlers) → Митигация: staged commits

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние |
|-----------|---------|
| `PipelineContainer` | `build_*_spec()` → `build_spec_for()` |
| `import_plan.py`, `enrich.py` | `_dataset_requires_vault()` → `build_spec_for("enrich")` |
| `registry.py` | `build_identity_index_plan()` → `build_spec_for("resolve")` |
| `OperationApplyAdapter` | Без изменений — принимает `PayloadBuilder` callable |
| `diagnostics/catalog.py` | Без изменений — `get_diagnostic_catalog()` остаётся typed |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-010](./TRANSFORM-PROBLEM-010-hardcoded-dataset-spec-blocks-extensibility.md) — решаемая проблема
- [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md) — OCP violation (решается Phase 2)
- [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md) — Phase 2 план (реализуется)
- `connector/datasets/spec.py` — DatasetSpec Protocol
- `datasets/registry.yml` — центральный реестр
- `datasets/employees.sink.yaml` — SinkSpec field metadata

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-09 | Решение предложено |
| 2026-03-09 | Решение принято |
