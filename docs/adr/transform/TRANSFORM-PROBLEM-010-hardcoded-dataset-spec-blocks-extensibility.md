# TRANSFORM-PROBLEM-010: Хардкодированный DatasetSpec блокирует расширяемость датасетов

> **Статус**: Решена в [TRANSFORM-DEC-009](./TRANSFORM-DEC-009-declarative-dataset-spec-yaml-driven-plugins.md)
> **Дата создания**: 2026-03-09
> **Затронутые компоненты**: `DatasetSpec`, `EmployeesSpec`, `build_user_upsert_payload`, `build_employees_catalog`, `registry.py`

---

## 📋 Контекст

Архитектура ETL-конвейера построена на DatasetSpec Protocol — контракте плагина датасета. Transform-стадии (map, normalize, enrich, match, resolve, sink) уже полностью декларативны: YAML-файлы в `datasets/` определяют правила трансформации, а `EmployeesSpec` просто делегирует к `load_*_spec_for_dataset(dataset_name)`.

Однако сам `EmployeesSpec` — единственная реализация `DatasetSpec` — остаётся хардкодированным Python-классом. Добавление нового датасета невозможно без написания Python-кода.

---

## ⚠️ Проблема

`EmployeesSpec` хардкодит в Python информацию, которая должна быть конфигурационной:

1. **ReportAdapter** — 3 строковых константы (`identity_label`, `conflict_code`, `conflict_field`)
2. **OperationApplyAdapter** — `operation_alias` + ссылки на Python-функции (`payload_builder`, `params_builder`)
3. **Payload builder** (`build_user_upsert_payload`) — валидация required полей, маппинг snake_case→camelCase, type coercion — дублирует метаданные из `employees.sink.yaml`
4. **Params builder** (`_build_employees_operation_params`) — извлечение `target_id` из `PlanItem`
5. **Diagnostic catalog** (`build_employees_catalog`) — 7 `CatalogEntry` с `diag_code`/`severity`/`message`
6. **Dataset registry** (`_registry = {"employees": make_employees_spec}`) — хардкодированный словарь фабрик

---

## 🔍 Симптомы

- **Симптом 1**: Добавление нового датасета требует создания Python-класса, функции-фабрики и регистрации в `_registry` — невозможно добавить датасет только через конфигурацию
- **Симптом 2**: `build_user_upsert_payload` дублирует field mappings из `employees.sink.yaml` (name→target, type, required/nullable)
- **Симптом 3**: `build_employees_catalog` хардкодит диагностические коды, которые по природе являются конфигурационными данными

---

## 📊 Масштаб проблемы

- **Частота**: При каждом добавлении нового датасета
- **Критичность**: Высокая — блокирует масштабирование: каждый датасет = Python-код + дублирование паттерна
- **Затронуто**: Все сценарии расширения: новые датасеты, новые целевые системы, кастомизация существующих датасетов

---

## 🧪 Как воспроизвести

1. Попытаться добавить новый датасет `departments` только через YAML
2. Создать `departments.source.yaml`, `departments.mapping.yaml`, ..., `departments.sink.yaml`
3. Добавить секцию в `datasets/registry.yml`
4. **Ожидаемый результат**: датасет доступен через `get_spec("departments")`
5. **Фактический результат**: `ValueError: Unsupported dataset: departments` — нет Python-класса `DepartmentsSpec` и записи в `_registry`

---

## 🚫 Почему это проблема?

- Нарушается extensibility: добавление датасета = изменение кода приложения
- Дублирование: `employees.sink.yaml` содержит все field mappings, но `build_user_upsert_payload` дублирует их вручную
- Хрупкость: изменение поля в sink.yaml требует синхронного изменения в payload builder
- Масштабирование: N датасетов = N Python-классов с идентичным boilerplate

---

## 💡 Возможные решения

### Вариант 1: Dataset DSL в registry.yml + Generic YamlDatasetSpec

- **Идея**: Расширить `registry.yml` секциями `report:`, `apply:`, `diagnostics:` per dataset. Создать generic `YamlDatasetSpec`, который читает всю конфигурацию из YAML. Payload builder строится из SinkSpec field metadata.
- **Плюсы**: Полная декларативность, zero Python для нового датасета, устранение дублирования
- **Минусы**: Нужен refactor payload builder, миграция registry

### Вариант 2: Отдельные dataset.yaml файлы

- **Идея**: Каждый датасет имеет `{dataset}.dataset.yaml` с report/apply/diagnostics
- **Плюсы**: Разделение concerns, один файл — один датасет
- **Минусы**: Ещё один уровень indirection, registry.yml уже играет эту роль

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md) — OCP violation в typed `build_*_spec()` методах
- [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md) — двухфазная эволюция DatasetSpec
- [TRANSFORM-DEC-009](./TRANSFORM-DEC-009-declarative-dataset-spec-yaml-driven-plugins.md) — принятое решение
- `connector/datasets/employees/spec.py` — `EmployeesSpec`
- `connector/datasets/registry.py` — хардкодированный реестр
- `connector/infra/target/providers/ankey_rest/payloads/users.py` — `build_user_upsert_payload`
- `datasets/employees.sink.yaml` — field mappings, дублируемые payload builder

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-09 | Проблема зафиксирована |
| 2026-03-09 | Решение принято в TRANSFORM-DEC-009 |
