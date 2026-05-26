# connector/domain/dsl

## Назначение

Универсальный движок трансформаций данных. Предоставляет реестр операций и исполнитель, который применяет цепочку DSL-операций к значению. Используется всеми стадиями пайплайна (mapping, normalize, enrich, …).

## Ключевые компоненты

| Файл | Назначение |
|---|---|
| `engine.py` | `TransformationEngine` — применяет `ops: list[OperationCall]` к значению последовательно; при исключении создаёт `DslIssue(code="DSL_OP_FAILED")` и прерывает цепочку |
| `registry.py` | `OperationRegistry` — реестр операций `name → callable`; `register_core_ops()` регистрирует ~44 встроенных операции |
| `ops.py` | Реализации всех встроенных операций: `trim`, `lower`, `concat`, `split_name`, `to_int`, `parse_bool`, `uuid`, `default_password`, `coalesce`, `map_each`, `format_mask` и др. |
| `diagnostics.py` | `DslIssue`, `translate_dsl_load_error()` — ошибки DSL-загрузки и выполнения |
| `issues.py` | `DslLoadError` — исключение при невалидной DSL-конфигурации |
| `build_options.py` | `BuildOptions` — настройки поведения движка (strict mode и др.) |
| `specs/` | Базовые Pydantic-модели: `OperationCall`, `TransformSpec` |
| `loader/` | `load_registry()` — загрузка `registry.yaml`; общие YAML-утилиты |

## Зависимости

**Зависит от:** `domain/diagnostics/`, stdlib.  
**Используется:** `domain/transform/` (все стадии), `infra/cache/sync/` (DSL sync adapter), `domain/transform_dsl/compilers/`.

## Расширение

Для добавления новой операции: добавить функцию в `ops.py`, зарегистрировать в `register_core_ops()`. Подробнее: `docs/dev/guides/how-to-add-dsl-operation.md`.
