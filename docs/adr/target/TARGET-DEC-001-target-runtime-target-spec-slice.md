# TARGET-DEC-001: TargetRuntime + target-spec slice для изоляции load-слоя от target-инфры

> **Статус**: Принято / реализовано (частично superseded [TARGET-DEC-003](./TARGET-DEC-003-target-core.md))
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

На момент фиксации проблемы команды `import_apply`, `cache_refresh`, `check_api` были связаны с Ankey-конкретной инфраструктурой на уровне delivery:
- wiring клиента/reader/executor происходил в командах и bootstrap;
- часть target-политик (retry/context/check endpoint) была размазана по нескольким точкам;
- тесты зависели от места импорта конкретных классов и были хрупкими к рефакторингу wiring.

Это блокировало развитие target-слоя как самостоятельного slice и усложняло путь к multi-target модели.

См. [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md).

---

## 🎯 Решение

Принято решение выделить единый target runtime слой в infra и зафиксировать его как единственную точку входа для delivery.

Ключевые положения решения:

1. Ввести `TargetRuntime` (`Protocol`) и `DefaultTargetRuntime` как production-фасад.
2. Сохранить usecase-контракты на доменных портах (`RequestExecutorProtocol`, `TargetPagedReaderProtocol`).
3. Централизовать target-specific правила в `TargetSpec` + `TargetKernel`.
4. Разделить ответственность `Gateway/Driver`:
   - driver = одна транспортная попытка;
   - gateway = единственный владелец retry-политики и нормализации ошибок.
5. Перевести `check_api` на `runtime.check()` и типизированный `TargetCheckResult`.
6. Собирать runtime через provider registry/factory, а не через ad-hoc bootstrap builders.

---

## 🏗️ Архитектурное решение

### Компоненты

| Компонент | Назначение | Файл |
|-----------|------------|------|
| `TargetRuntime` / `DefaultTargetRuntime` | фасад для delivery (`executor`, `reader`, `check`, `meta`, `stats`) | `connector/infra/target/core/runtime.py` |
| `TargetKernel` | спецификация операций, fault/retry/redaction resolution | `connector/infra/target/core/kernel.py` |
| `TargetGateway` | execution/read/check + retry owner | `connector/infra/target/core/gateway.py` |
| `TargetDriver` contract | транспортный single-attempt контракт | `connector/infra/target/driver.py` |
| Factory + Registry | сборка runtime через provider | `connector/infra/target/core/factory.py`, `connector/infra/target/core/registry.py` |
| Typed boundary models | `TargetMeta`, `TargetStats`, `TargetCheckResult` | `connector/infra/target/core/models.py` |

### Интерфейсная граница

```python
class TargetRuntime(Protocol):
    @property
    def executor(self) -> RequestExecutorProtocol: ...
    @property
    def reader(self) -> TargetPagedReaderProtocol | None: ...

    def check(self) -> TargetCheckResult: ...
    def meta(self) -> TargetMeta: ...
    def stats(self) -> TargetStats: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...
```

### Поток данных

```
Delivery command
   -> build_target_runtime_with_info(...)
   -> runtime.executor / runtime.reader / runtime.check()
   -> TargetGateway (rules from TargetKernel)
   -> TargetDriver (single attempt I/O)
   -> target system
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ единая точка ответственности за target wiring и policy;
- ✅ cleaner-грань между delivery/usecase/infra;
- ✅ снижение хрупкости e2e/integration тестов (patch фабрики вместо конкретных классов);
- ✅ подготовка к provider-модели и operation alias контракту.

**Компромиссы**:
- ⚠️ target-slice стал более явным и многокомпонентным;
- ⚠️ требуется строгий guard на импортные границы, чтобы не вернуться к “встроенному” wiring в командах.

**Отклонённые альтернативы**:
- ❌ оставить bootstrap-строители `build_api_*` и точечные рефакторы;
- ❌ ввести общий DI-контейнер для всего приложения на этом этапе;
- ❌ оставить retry/check/error-polices распределёнными по слоям.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/bootstrap.py` | подключены `build_target_runtime*` из target-core factory |
| `connector/delivery/commands/import_apply.py` | use-case получает `runtime.executor` |
| `connector/delivery/commands/cache_refresh.py` | refresh использует `runtime.reader` |
| `connector/delivery/commands/check_api.py` | API-check через `runtime.check()` |
| `connector/infra/target/providers/registry.py` | default provider registry |
| `connector/infra/target/providers/ankey_rest/provider.py` | provider wiring на core-компонентах |

### Этапы внедрения (фактически)

1. Сначала введён runtime-контракт и базовая factory-сборка.
2. Затем команды `import_apply`, `cache_refresh`, `check_api` переведены на runtime.
3. После стабилизации wiring закреплены архитектурные guard-тесты.
4. Дальнейшая консолидация provider/core-границ вынесена в [TARGET-DEC-003](./TARGET-DEC-003-target-core.md).

### Инварианты

1. Delivery-команды не импортируют `connector.infra.http.*` и Ankey-specific классы напрямую.
2. Usecases/domain не импортируют `connector.infra.target.*`.
3. Retry выполняется только в `TargetGateway`.
4. Driver не содержит policy-retry и выполняет одну I/O попытку.
5. Runtime metadata/stats остаются типизированными.
6. На текущем этапе поддерживается только runtime mode `core`.

---

## 🧪 Валидация решения

- Архитектурные guard-тесты: `tests/architecture/test_target_layer_boundaries.py`.
- Unit:
  - `tests/unit/infrastructure/test_target_factory.py`
  - `tests/unit/infrastructure/test_target_runtime.py`
  - `tests/unit/infrastructure/test_target_gateway.py`
- E2E/интеграционные сценарии команд используют `build_target_runtime_with_info(...)` как единый вход.

---

## ⚠️ Риски и ограничения

- Пока в production-реестре один provider (`ankey`), поэтому multi-provider сценарии ограничены unit-контрактами.
- Дальнейшая стабилизация provider model, contracts и cleanup зафиксирована в [TARGET-DEC-003](./TARGET-DEC-003-target-core.md).

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| Delivery commands | Прямое | использование `runtime` вместо прямого target client wiring |
| Usecases apply/read | Косвенное | контракты портов сохранены, wiring стал чище |
| Target infra | Прямое | введён единый pipeline `runtime -> gateway -> driver` |
| Тесты | Прямое | переход к patch factory/runtime вместо patch конкретных классов |

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md)
- [TARGET-DEC-002](./TARGET-DEC-002-usecase-apply-result-presenter.md)
- [TARGET-DEC-003](./TARGET-DEC-003-target-core.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено и принято |
| 2026-02-13 | Зафиксирован подход: `TargetRuntime` + `TargetSpec` + `Gateway/Driver` |
| 2026-02-16 | Реализация переведена на provider-based runtime wiring |
| 2026-02-16 | Часть решения консолидирована и расширена в [TARGET-DEC-003](./TARGET-DEC-003-target-core.md) |
