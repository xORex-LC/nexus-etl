# TARGET-DEC-003: TargetCore как plugin-core (core механики + provider-правила)

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-16
> **Решает проблему**: [TARGET-PROBLEM-003](./TARGET-PROBLEM-003-target-core.md)
> **Частично supersede**: [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После внедрения `TargetRuntime` в [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) остался открытый архитектурный вопрос: как зафиксировать целевой target-core так, чтобы:
- механики не размазывались по providers/commands;
- provider-specific правила оставались локальными;
- legacy-path не возвращался;
- внешние зависимости (`tenacity`, `structlog`, transport libs) не утекали в domain/usecase/delivery.

См. [TARGET-PROBLEM-003](./TARGET-PROBLEM-003-target-core.md).

---

## 🎯 Решение

Принята plugin-core модель Target слоя.

Ключевые положения:

1. `TargetCore` реализует agnostic-механики и runtime-фасад.
2. Provider реализует transport-specific детали и собственный `TargetSpec`.
3. Правила поведения описываются декларативно в spec:
   - `fault_rules`
   - `retry_rules`
   - operation catalog (`OperationSpec` + alias)
4. Retry policy owner — core gateway; driver выполняет single-attempt I/O.
5. Legacy target-path удалён; runtime работает в `core` режиме.
6. Фиксируются минимальные стабильные контракты fault/retry и boundaries импортов.

---

## 🏗️ Архитектурное решение

### Core слой

| Модуль | Ответственность |
|--------|------------------|
| `connector/infra/target/core/runtime.py` | фасад runtime и выдача портов для delivery |
| `connector/infra/target/core/kernel.py` | fault/retry resolution, operation lookup, redaction helpers |
| `connector/infra/target/core/gateway.py` | execute/read/check orchestration + retry owner |
| `connector/infra/target/core/spec_models.py` | типы `TargetSpec`, `OperationSpec`, `RetryRule`, `RetryConfig` |
| `connector/infra/target/core/engines/*` | retry engine, safe logging, normalizer/result builder |
| `connector/infra/target/core/factory.py` + `registry.py` | сборка runtime через provider registry |

### Provider слой

| Модуль | Ответственность |
|--------|------------------|
| `connector/infra/target/providers/ankey_rest/spec.py` | каталог операций и правила Ankey |
| `connector/infra/target/providers/ankey_rest/driver.py` | transport-driver с одной попыткой |
| `connector/infra/target/providers/ankey_rest/provider.py` | wiring provider -> core runtime |

### Зафиксированные контракты v1

- Fault kinds: `SPEC`, `AUTH`, `PERMISSION`, `DATA`, `NOT_FOUND`, `CONFLICT`, `THROTTLE`, `TRANSIENT`, `UNKNOWN`.
- Retry directives: `NO_RETRY`, `RETRY_BACKOFF`, `RETRY_AFTER`, `ESCALATE` (+ optional mutation hook в rule).
- Operation model: alias-first (`users.upsert`, `users.list`, `health.check`) с transport payload в `OperationSpec.data`.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ единая и расширяемая архитектура target-slice;
- ✅ предсказуемое разделение mechanism vs rules;
- ✅ легче добавлять новый target-type как provider;
- ✅ legacy cleanup закрывает источник регрессий границ.

**Компромиссы**:
- ⚠️ core требует дисциплины по контрактам и guard-тестам;
- ⚠️ один provider в production ограничивает практическую проверку multi-provider поведения.

**Отклонённые альтернативы**:
- ❌ поддерживать параллельно long-lived legacy/core paths;
- ❌ держать transport-specific логику в core;
- ❌ разносить retry/error/redaction rules по разным слоям без единого spec owner.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/target/core/spec_models.py` | pydantic-модели target-спеки и operation catalog |
| `connector/infra/target/core/kernel.py` | централизованное rule resolution |
| `connector/infra/target/core/gateway.py` | единый retry owner и target execution pipeline |
| `connector/infra/target/core/engines/retry_engine.py` | retry/backoff engine на `tenacity` |
| `connector/infra/target/core/engines/safe_logging.py` | safe logging/redaction с `structlog` |
| `connector/infra/target/core/factory.py` | core-only runtime mode и provider selection |
| `connector/infra/target/providers/ankey_rest/*` | provider-first реализация Ankey |

### Этапы консолидации (фактически)

1. Зафиксированы core contracts (`spec_models`, `kernel`, `gateway`) и provider responsibilities.
2. Перенесены retry/safe-logging механики в core engines и ограничены архитектурными guard-тестами.
3. Удалены legacy target-path и legacy bootstrap builders.
4. Factory/runtime policy окончательно зафиксирована как core-only.

### Инварианты

1. `domain/usecases/delivery` не импортируют `httpx/tenacity/structlog`.
2. Core не содержит provider-specific literals (`resourceexists`, hardcoded health alias).
3. Provider не владеет retry engine.
4. Legacy target-файлы и legacy bootstrap builders отсутствуют в репозитории.
5. Factory принимает только `runtime_mode='core'`.
6. Operation aliases являются публичным контрактом target-вызовов.

---

## 🧪 Валидация решения

- Архитектурные guard-тесты:
  - `tests/architecture/test_target_layer_boundaries.py`
- Unit target-core:
  - `tests/unit/infrastructure/test_target_spec.py`
  - `tests/unit/infrastructure/test_target_kernel.py`
  - `tests/unit/infrastructure/test_target_gateway.py`
  - `tests/unit/infrastructure/test_target_factory.py`
- Performance smoke:
  - `tests/performance/target/test_bench_target_runtime.py`

---

## ⚠️ Риски и ограничения

- Текущая production-проверка ограничена одним provider (`ankey`).
- Расширение на новые target-типы потребует соблюдения alias и retry/fault contracts в новых provider-spec.
- Любое изменение `TargetSpec` должно сопровождаться синхронным обновлением unit + architecture guards.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `TARGET-DEC-001` область | Прямое | эволюция из runtime-cleanup в каноничную plugin-core модель |
| Delivery команды | Косвенное | продолжают работать через `build_target_runtime_with_info` и typed runtime |
| Dataset adapters | Косвенное | operation alias и provider payload contracts становятся стабильным интерфейсом |
| Тестовая архитектура | Прямое | усилены guard-тесты по cleanup и импортным границам |

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-003](./TARGET-PROBLEM-003-target-core.md)
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md)
- [TARGET-DEC-002](./TARGET-DEC-002-usecase-apply-result-presenter.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-16 | Решение предложено и принято как каноничное для target-core |
| 2026-02-16 | Зафиксирована модель `mechanism in core / rules in provider spec` |
| 2026-02-16 | Завершён cleanup legacy target-path, закреплён core-only runtime |
| 2026-02-17 | ADR синхронизирован с фактической структурой кода и guard-тестами |
