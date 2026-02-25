# TARGET-DEC-004: target-dsl — YAML-описание поведенческой спецификации провайдера

> **Статус**: Принято / реализовано
> **Дата принятия**: 2026-02-17
> **Решает проблему**: [TARGET-PROBLEM-004](./TARGET-PROBLEM-004-hardcoded-provider-spec.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

TargetCore (TARGET-DEC-003) правильно моделирует поведение провайдера через `TargetSpec`,
но spec создаётся программно (`build_ankey_spec()`). Нужно дать возможность задавать spec
декларативно в YAML, следуя паттерну `datasets/*.yaml`, уже принятому в transform-слое
(TARGET-PROBLEM-004).

---

## 🎯 Решение

Создать `connector/domain/target_dsl/` — модуль, который:
1. Читает `datasets/registry.yml`, находит путь к YAML-файлу по `targets.{target_type}`.
2. Загружает YAML, инжектирует `alias` в операции из ключей словаря.
3. Валидирует через `TargetSpec.model_validate()` (Pydantic v2 коэрцирует list→tuple/frozenset).
4. Оборачивает ошибки в `DslLoadError` для согласованной диагностики.

Промежуточный `TargetDslSpec` не нужен: `TargetSpec` уже является правильной Pydantic-моделью
с `extra="forbid"`, `frozen=True` и всеми необходимыми model_validators.

---

## 🏗️ Архитектурное решение

### Новые компоненты

- **`connector/domain/target_dsl/__init__.py`** — публичный API: `load_target_spec(target_type: str) → TargetSpec`
- **`connector/domain/target_dsl/loader.py`** — YAML-загрузка + alias injection + `TargetSpec.model_validate()`
- **`datasets/targets/ankey.target.yaml`** — декларативная spec Ankey IDM

### Изменения в существующих компонентах

- **`connector/domain/dsl/loader/__init__.py`** — реэкспортировать generic утилиты из `_common.py` с публичными именами (`read_yaml`, `find_repo_root`, `load_registry`, `validate_spec`, `load_spec_from_path`)
- **`connector/domain/dsl/__init__.py`** — добавить `DslBaseModel` в публичный API
- **`datasets/registry.yml`** — добавить секцию `targets:`
- **`connector/infra/target/providers/ankey_rest/provider.py`** — `load_target_spec("ankey")` вместо `build_ankey_spec()`
- **`connector/infra/target/providers/ankey_rest/spec.py`** — удалить (становится избыточным)

### Поток данных

```
datasets/registry.yml
    ↓  targets.{target_type} → relative path
datasets/targets/ankey.target.yaml
    ↓  read_yaml → dict
_inject_aliases: operations[key]["alias"] = key (для каждого ключа)
    ↓
TargetSpec.model_validate(dict)
    ↓  Pydantic: list → tuple[FaultRule,...], list → frozenset[TargetCapability]
TargetSpec (frozen, validated)
    ↓
AnkeyTargetProvider.build_core_runtime(spec, settings)
    ↓
TargetRuntime
```

### Граница: YAML vs Python

| В YAML (декларативно) | В Python (остаётся в коде) |
|-----------------------|---------------------------|
| `capabilities` | `AnkeyAuth` (httpx.Auth адаптер) |
| `fault_rules` | `AnkeyPagingStrategy` (алгоритм пейджинга) |
| `retry_rules` (+ имена мутаций) | `regenerate_target_id` (функция-мутация) |
| `retry_config` | `AnkeyHttpDriver` (сборка transport layer) |
| `redaction` | `AnkeyTargetProvider` (wiring: auth+driver+gateway+runtime) |
| `health` + `operations` | |

Мутации и auth — это Python-алгоритмы и инфраструктурные секреты, а не конфигурация.
Ссылки на мутации (строковые имена) остаются в YAML (`retry_rules[].mutation`), сами
функции регистрируются в `TargetMutationRegistry`.

### YAML-схема (ключевые аспекты)

```yaml
target_type: ankey            # → TargetSpec.target_type
capabilities: [check, ...]    # list → frozenset[TargetCapability] (Pydantic коэрция)
fault_rules:                  # list → tuple[FaultRule,...] (Pydantic коэрция)
  - fault_kind: AUTH
    match_status: 401
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id   # строковая ссылка на зарегистрированную мутацию
operations:                   # dict[alias → OperationSpec без поля alias]
  users.upsert:               # ← alias инжектируется автоматически из этого ключа
    expected_statuses: [200, 201]
    data: {method: PUT, path_template: /ankey/managed/user/{target_id}, ...}
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Провайдер добавляется одним YAML-файлом + один Python-файл (auth/driver/provider wiring)
- ✅ `TargetSpec` остаётся единственным source of truth — нет дублирования модели
- ✅ Pydantic v2 коэрция list→tuple/frozenset работает нативно, без дополнительного кода
- ✅ `DslLoadError` из dsl-core обеспечивает согласованную диагностику ошибок загрузки
- ✅ Паттерн полностью симметричен transform-DSL: YAML → loader → runtime object
- ✅ fault_rules/retry_rules можно менять без деплоя кода

**Недостатки (компромиссы)**:
- ⚠️ Мутации не декларативны (имена в YAML, функции в коде) — приемлемо: мутации — это
  Python-алгоритмы (генерация UUID, трансформации), а не конфигурация
- ⚠️ Auth и paging остаются в коде — провайдер всё ещё требует Python-файл, но это правильно:
  auth — это инфраструктурные учётные данные, не публичная спецификация

**Альтернативы, которые отклонили**:
- ❌ **Расширить `dsl/specs/` и `dsl/loader/`**: смешивает transform-DSL (правила обработки
  данных) с infrastructure-DSL (описание внешнего API) в одном пакете — нарушает SRP
- ❌ **Промежуточный `TargetDslSpec`**: дублирует `TargetSpec` без ценности; Pydantic v2
  коэрция устраняет необходимость в YAML-friendly промежуточной модели

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/target_dsl/__init__.py` | Создан, экспортирует `load_target_spec` |
| `connector/domain/target_dsl/loader.py` | Создан: YAML → alias injection → `TargetSpec.model_validate()` |
| `connector/domain/dsl/loader/__init__.py` | +публичные реэкспорты generic утилит |
| `connector/domain/dsl/__init__.py` | +`DslBaseModel` в `__all__` |
| `datasets/targets/ankey.target.yaml` | Создан: полная spec Ankey IDM |
| `datasets/registry.yml` | +секция `targets:` |
| `providers/ankey_rest/provider.py` | `load_target_spec("ankey")` вместо `build_ankey_spec()` |
| `providers/ankey_rest/spec.py` | Удалён |

### Ключевые методы

- `load_target_spec(target_type: str) → TargetSpec` — публичный API target-dsl
- `_inject_aliases(operations: dict) → dict` — инжекция alias из ключа в операцию

### Инварианты

1. **YAML → `TargetSpec`**: всегда через `TargetSpec.model_validate()` — никакого обхода валидаторов
2. **Fail-fast**: ошибки в YAML поднимают `DslLoadError` с указанием пути и контекста
3. **Неизменяемость**: `TargetSpec` frozen — после загрузки spec не изменяется

---

## 🧪 Валидация решения

**Тесты**:
- `test_load_target_spec_ankey()` — загрузить YAML, assert target_type, capabilities, len(operations)
- `test_missing_target_raises_dsl_error()` — несуществующий target_type → `DslLoadError`
- `test_invalid_fault_rule_raises()` — YAML с отсутствующим matcher → `DslLoadError` с описанием
- `test_alias_injected_correctly()` — alias из ключа совпадает с `OperationSpec.alias`
- smoke-тест провайдера: `build_core_runtime()` без ошибок, `meta().target_type == "ankey"`

**Метрики успеха**:
- Все существующие тесты (`pytest tests/`) проходят без изменений
- `load_target_spec("ankey")` возвращает `TargetSpec` идентичный прежнему `build_ankey_spec()`

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `operations.data` остаётся `dict[str, Any]` — transport-специфика не типизирована в YAML.
  Валидация происходит позже в `TransportCompilerRegistry` при инициализации `TargetKernel`.

**Риски**:
- ⚠️ YAML требует правильного порядка `fault_rules` (как и Python-вариант)
  → Митигация: Pydantic валидирует каждый `FaultRule` при загрузке (fail-fast)
- ⚠️ Опечатка в `target_type` в YAML не будет поймана до runtime
  → Митигация: `DslLoadError` с явным сообщением при поиске в registry

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `AnkeyTargetProvider` | Использует новый API | `load_target_spec("ankey")` вместо `build_ankey_spec()` |
| `dsl-core` | Незначительное | Реэкспорт generic утилит в публичном API |
| Будущие провайдеры | Положительное | YAML-файл + провайдер без Python spec-функции |

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-004](./TARGET-PROBLEM-004-hardcoded-provider-spec.md) — решаемая проблема
- [TARGET-DEC-003](./TARGET-DEC-003-target-core.md) — TargetCore архитектура (TargetSpec/TargetRuntime)
- [DSL-DEC-002](../dsl/DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — dsl-core модуляризация

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-17 | Решение предложено и принято |
| 2026-02-17 | Реализовано: target_dsl модуль создан, Ankey мигрирован |
