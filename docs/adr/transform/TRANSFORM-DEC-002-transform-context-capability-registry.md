# TRANSFORM-DEC-002: TransformContext — typed capability registry для transform-зависимостей

> **Статус**: Поглощено [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — TransformContext эволюционировал в StageExecutionContext как часть целостной pipeline-архитектуры
> **Дата принятия**: 2026-02-20
> **Решает проблему**: [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`TransformProviderDeps` — flat dataclass с полями `cache_gateway`, `secret_store`, `dictionaries`. При добавлении Dictionary Layer обнаружено, что `cache_gateway` объявлен обязательным, хотя ряд use-cases использует только `dictionaries`. Проблема описана в [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md).

Кроме того, при добавлении каждой новой capability deps-объект будет расти как catch-all без declarative capability-семантики. Нет механизма проверить "у меня достаточно зависимостей для этого набора enrich-правил" на этапе сборки pipeline.

---

## ⚠️ Временная митигация (применена, остаётся до реализации TransformContext)

Как минимальный stopgap в `connector/domain/transform/providers/deps.py` сделано:

```python
# было
cache_gateway: EnrichLookupPort           # обязателен

# стало — митигация Вариант A
cache_gateway: EnrichLookupPort | None = None
```

Это устраняет немедленный boilerplate при dictionary-only usage. Не меняет архитектурный контракт — TransformProviderDeps остаётся flat catch-all.

---

## 🎯 Решение

Заменить `TransformProviderDeps` на `TransformContext` — typed capability registry, индексированный по типу порта.

Каждый provider запрашивает только то, что ему нужно: `ctx.require(EnrichLookupPort)` — получает порт или получает чёткий `AttributeError` с именем порта. Нет неиспользуемых зависимостей, нет catch-all.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новый класс** `TransformContext` в `connector/domain/transform/providers/context.py`:

```python
from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


class TransformContext:
    """
    Typed capability registry for transform stage dependencies.

    Pay-for-what-you-use: каждый provider запрашивает только нужную capability.
    Extensible: добавление новой capability не меняет публичный API.

    Назначение:
        Заменяет TransformProviderDeps, устраняя обязательный catch-all coupling.
    """

    def __init__(self, registry: dict[type, object]) -> None:
        self._registry = registry

    def require(self, port_type: type[T]) -> T:
        """
        Получить capability или raise AttributeError с диагностическим сообщением.

        Используется provider-функциями, для которых данная capability обязательна.
        """
        instance = self._registry.get(port_type)
        if instance is None:
            raise AttributeError(
                f"Capability '{port_type.__name__}' not registered in TransformContext. "
                f"Registered: {[t.__name__ for t in self._registry]}"
            )
        return instance  # type: ignore[return-value]

    def get(self, port_type: type[T]) -> T | None:
        """Получить capability или None."""
        return self._registry.get(port_type)  # type: ignore[return-value]

    def has(self, port_type: type) -> bool:
        """Проверить наличие capability."""
        return port_type in self._registry

    @classmethod
    def build(
        cls,
        *,
        cache: EnrichLookupPort | None = None,
        dictionaries: DictionaryProviderPort | None = None,
        secrets: SecretStoreProtocol | None = None,
    ) -> "TransformContext":
        """
        Построить TransformContext из именованных capability-параметров.

        Только не-None capabilities регистрируются. Это и есть "pay for what you use".
        """
        registry: dict[type, object] = {}
        if cache is not None:
            registry[EnrichLookupPort] = cache  # type: ignore[misc]
        if dictionaries is not None:
            registry[DictionaryProviderPort] = dictionaries  # type: ignore[misc]
        if secrets is not None:
            registry[SecretStoreProtocol] = secrets  # type: ignore[misc]
        return cls(registry)
```

**Изменения в `connector/domain/transform/providers/registry.py`** (provider-функции):

```python
# до
def _cache_by_field(deps: Any, value: Any, *, args) -> list[dict]:
    cache_gateway = getattr(deps, "cache_gateway", None)
    if cache_gateway is None:
        raise AttributeError("deps.cache_gateway is required for provider 'cache.by_field'")
    ...

def _dictionary_by_key(deps: Any, value: Any, *, args) -> list[dict]:
    dictionaries = _require_dictionaries(deps, provider_name="dictionary.by_key")
    ...

# после — deps -> ctx: TransformContext
def _cache_by_field(ctx: TransformContext, value: Any, *, args) -> list[dict]:
    cache = ctx.require(EnrichLookupPort)
    ...

def _dictionary_by_key(ctx: TransformContext, value: Any, *, args) -> list[dict]:
    dicts = ctx.require(DictionaryProviderPort)
    ...
```

**Изменения в wiring** (`connector/delivery/cli/containers.py`, `connector/datasets/employees/spec.py`):

```python
# до
enrich_deps = TransformProviderDeps(
    cache_gateway=enrich_lookup,
    secret_store=secret_store,
    dictionaries=dictionaries,
)

# после
enrich_deps = TransformContext.build(
    cache=enrich_lookup,
    dictionaries=dictionaries,
    secrets=secret_store,
)
```

### Поток данных

```
DatasetSpec.build_enrich_deps()
    └─> TransformContext.build(cache=..., dictionaries=..., secrets=...)
          └─> Регистрирует только не-None capabilities
              ↓
EnricherEngine(deps=ctx)
    └─> EnricherCore.deps = ctx
        └─> _DslLookupProvider.fetch()
              └─> ProviderGateway.lookup(name, ctx, value, args=...)
                    └─> _cache_by_field(ctx, value, args)
                          └─> ctx.require(EnrichLookupPort) → typed access
```

### Конвенция для новых stages (фиксируется здесь)

| Ситуация | Паттерн |
|----------|---------|
| Stage с YAML-конфигурируемыми провайдерами (разные источники в одном DSL-правиле) | `TransformContext` + ProviderGateway |
| Stage со статическим одним портом (порт определён в коде, не в YAML) | Прямая port-инъекция в конструктор (паттерн Match/Resolve) |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Истинный "pay for what you use": provider декларирует только нужную capability
- ✅ Масштабируется без изменения API: добавить 10-ю capability — только `ctx.build(new_port=...)`
- ✅ Чёткая диагностика: `AttributeError` с именем порта и списком зарегистрированных
- ✅ Open/closed: новые провайдеры и capabilities не меняют контракт
- ✅ Унифицированный паттерн для YAML-конфигурируемых stages

**Недостатки (компромиссы)**:
- ⚠️ `ctx.require(SomePort)` — слабее IDE autocomplete чем `deps.cache_gateway` (нет статического completion на атрибуте)
- ⚠️ Высокая стоимость рефактора: deps.py + registry.py + все provider-функции + spec.py + containers.py + usecases + тесты
- ⚠️ Потенциально слабее статические гарантии: `type[T] → T` через dict хуже, чем dataclass-атрибут

**Альтернативы, которые отклонили**:
- ❌ **Вариант A (only)**: Снимает симптом, не решает root cause — dataclass продолжает расти как catch-all
- ❌ **Вариант B (Protocol structural)**: Python Protocol runtime-checking громоздкий; нет выигрыша над TransformContext при текущем масштабе

---

## 🛠️ Реализация (при достижении trigger-критериев)

### Trigger-критерии для начала реализации

Переход к TransformContext **обязателен** при достижении **любого** из:

- 5+ capability-полей в deps-объекте — OR
- 3+ `DatasetSpec`-реализаций с разными capability-профилями (одни используют только dict, другие только cache, третьи всё) — OR
- Явная потребность в plugin-style расширении провайдеров из разных модулей (не из registry.py)

### Ключевые файлы (при реализации)

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/providers/context.py` | Создать `TransformContext` |
| `connector/domain/transform/providers/deps.py` | Удалить `TransformProviderDeps` или сохранить как alias на период перехода |
| `connector/domain/transform/providers/registry.py` | Provider-функции: `deps: Any` → `ctx: TransformContext` |
| `connector/datasets/spec.py` | Обновить `DatasetSpec.build_enrich_deps()` return type |
| `connector/datasets/employees/spec.py` | `build_enrich_deps()` → `TransformContext.build(...)` |
| `connector/delivery/cli/containers.py` | Wiring: `TransformContext.build(...)` |
| `connector/usecases/import_plan_service.py` | Обновить вызов `build_enrich_deps()` |
| `tests/unit/transform/test_stage_builders.py` | Обновить fixtures |
| `tests/unit/transform/test_provider_registry.py` | `_DummyDeps` → `TransformContext` |

### Инварианты

1. `TransformContext.require()` никогда не возвращает `None` — либо возвращает порт, либо `AttributeError`
2. `TransformContext.build()` регистрирует только не-`None` capabilities (нет phantom registrations)
3. Provider-функции не обращаются к `deps`/`ctx` напрямую через `getattr` — только через `ctx.require()` / `ctx.get()`

---

## 🧪 Валидация решения (при реализации)

**Тесты**:
- ✅ `test_context_require_raises_on_missing_capability()` — чёткий `AttributeError`
- ✅ `test_context_get_returns_none_on_missing()` — мягкое отсутствие
- ✅ `test_context_build_skips_none_capabilities()` — не регистрирует None
- ✅ `test_cache_provider_uses_context_require()` — провайдер получает порт через ctx
- ✅ `test_dictionary_only_context_without_cache()` — dictionary без cache работает

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Ослабленный статический анализ: `ctx.require(SomePort)` не проверяется mypy без дополнительных overload-стабов

**Риски**:
- ⚠️ Ошибочная регистрация неправильного типа порта → runtime `AttributeError` вместо compile-time
  - **Митигация**: `TransformContext.build()` — типизированный builder с явными keyword-параметрами; ошибки отлавливаются на wiring

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `TransformProviderDeps` | Удаляется / alias | Заменяется `TransformContext` |
| `ProviderGateway` provider-функции | Medium | `deps: Any` → `ctx: TransformContext`, `getattr` → `ctx.require()` |
| `DatasetSpec` / `EmployeesSpec` | Medium | `build_enrich_deps()` return type + внутренняя конструкция |
| `containers.py` / `import_plan_service.py` | Minimal | Wiring update |
| Тесты | Medium | Fixture rebuild |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — решаемая проблема
- `connector/domain/transform/providers/deps.py` — временная митигация (Вариант A)
- `connector/domain/transform/providers/registry.py` — provider-функции, которые будут обновлены

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-20 | Проблема TRANSFORM-PROBLEM-002 обнаружена, решение предложено |
| 2026-02-20 | Временная митигация Вариант A применена: `cache_gateway: EnrichLookupPort \| None = None` |
| 2026-02-20 | TransformContext зафиксирован как целевая архитектура, статус: Предложено |
| 2026-02-22 | Поглощено TRANSFORM-DEC-004: TransformContext → StageExecutionContext в составе целостной pipeline-архитектуры |
