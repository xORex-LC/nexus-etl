# TARGET-DEC-001: TargetRuntime + target-spec slice для изоляции load-слоя от target-инфры

> **Статус**: Предложено
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-001](./target/TARGET-PROBLEM-001-load-layer-target-wiring.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

В текущей реализации `apply/refresh/check_api` в delivery-слое напрямую “знают” о конкретном target (Ankey IDM): сборка клиента/экзекьютора/ридера и часть target-специфики размазаны по `delivery/cli/bootstrap.py` и командам.

Это приводит к:
- сцеплению delivery ↔ infra-реализациями (и исключениями) target;
- дублированию wiring и политик подключения;
- усложнению тестирования (хрупкий monkeypatch);
- затруднению расширения на другие target-типовые реализации (API/DB/File).

См. [TARGET-PROBLEM-001](./target/TARGET-PROBLEM-001-load-layer-target-wiring.md).

---

## 🎯 Решение

1) Ввести **TargetRuntime** как **infra-артефакт** (не доменный порт) — единую точку доступа к инструментам target-системы (API/DB/File) для delivery-команд.

2) За TargetRuntime держать **строгую target-specific спецификацию** (в духе cache слоя):
- `TargetSpec`: описывает поддерживаемые операции/эндпоинты/ожидаемые статусы/ошибки/нюансы сервера;
- `TargetKernel`: валидирует/нормализует спецификацию и предоставляет “операции” в удобном виде.

3) Взаимодействие с target выполнять через **gateway/driver**:
- `TargetDriver` (transport): отвечает за низкоуровневый I/O (HTTP/DB/File, auth, ssl, retries);
- `TargetGateway`: переводит потребности приложения в операции target, используя `TargetKernel` и `TargetDriver`.

4) Доменные порты **не менять**:
- `apply` (usecase) продолжает работать через `RequestExecutorProtocol`/`TargetPagedReaderProtocol`.
- `TargetRuntime` предоставляет реализации этих портов наружу (delivery/usecases), скрывая конкретный target.

5) `check_api` переводится на `TargetRuntime.check()` — delivery больше не импортирует `ApiError` и не знает “какой endpoint пинговать”.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули** (infra):
- `TargetRuntime` в `connector/infra/target/runtime.py`
  - `executor: RequestExecutorProtocol`
  - `reader: TargetPagedReaderProtocol | None`
  - `check(): TargetCheckResult`
  - `meta()/stats()/reset()` (минимальный сервисный API)
- `TargetSpec` в `connector/infra/target/spec/*.py` (пока код-спека, позже — декларативно)
- `TargetKernel` в `connector/infra/target/kernel.py`
- `TargetGateway` в `connector/infra/target/gateway.py`
- `TargetDriver` (transport) в `connector/infra/target/driver/*.py`

**Изменения в существующих компонентах**:
- `connector/delivery/cli/bootstrap.py`:
  - убрать `build_api_client/build_api_executor/build_api_reader`
  - добавить `build_target_runtime(...)`
- Команды:
  - `import_apply.py` использует `runtime.executor`
  - `cache_refresh.py` использует `runtime.reader`
  - `check_api.py` использует `runtime.check()`

### Интерфейсы

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol

from connector.domain.ports.target.execution import RequestExecutorProtocol
from connector.domain.ports.target.reader import TargetPagedReaderProtocol
from connector.domain.diagnostics.policies import SystemErrorCode


@dataclass(frozen=True)
class TargetCheckResult:
    ok: bool
    latency_ms: int | None = None
    error_code: SystemErrorCode | None = None
    error_message: str | None = None


class TargetRuntime(Protocol):
    executor: RequestExecutorProtocol
    reader: TargetPagedReaderProtocol | None

    def reset(self) -> None: ...
    def stats(self) -> dict[str, Any]: ...
    def meta(self) -> dict[str, Any]: ...
    def check(self) -> TargetCheckResult: ...
```

### Поток данных

```
Plan(JSON) → ImportApplyService → dataset ApplyAdapter → RequestSpec(+payload)
                                     ↓
                             RequestExecutorProtocol
                                     ↓
                           TargetRuntime.executor
                                     ↓
                      TargetGateway (uses TargetKernel)
                                     ↓
                 TargetDriver/Transport (HTTP/DB/File I/O)
                                     ↓
                               Target system
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Delivery перестаёт знать конкретный target (Ankey) и его исключения/эндпоинты.
- ✅ Единая точка wiring и политик подключения (timeouts/retry/backoff/transport).
- ✅ Улучшение тестируемости: monkeypatch одной фабрики (`build_target_runtime`), а не импортов конкретных клиентов.
- ✅ Target-специфика централизована и готова к будущей декларативизации (DSL/YAML/OpenAPI).

**Недостатки (компромиссы)**:
- ⚠️ Добавляет несколько infra-компонентов (Spec/Kernel/Gateway/Driver), но это локализовано в одном target-slice.
- ⚠️ Переход возможен инкрементально: на первом этапе dataset ApplyAdapter может продолжать собирать `RequestSpec`.

**Альтернативы, которые отклонили**:
- ❌ Оставить всё в `bootstrap.py` и командах: закрепляет сцепление и копипасту, ухудшает расширяемость.
- ❌ Сразу переводить `plan/apply` на DSL: сейчас даёт мало выигрыша и увеличивает сложность без закрытия root-cause в load-слое.
- ❌ Вводить общий DI-контейнер на всё приложение: риск оверинжиниринга; для target-cleanup достаточно TargetRuntime.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/target/runtime.py` | Новый `TargetRuntime` (инфра-артефакт) |
| `connector/infra/target/spec/*` | `TargetSpec` для Ankey (код-спека) |
| `connector/infra/target/kernel.py` | `TargetKernel` (валидация/нормализация спеки) |
| `connector/infra/target/gateway.py` | `TargetGateway` (перевод операций в driver calls) |
| `connector/infra/target/driver/*` | `TargetDriver` (transport: http/db/file) |
| `connector/delivery/cli/bootstrap.py` | Заменить `build_api_*` на `build_target_runtime` |
| `connector/delivery/commands/check_api.py` | Использовать `runtime.check()` вместо прямого клиента |
| `connector/delivery/commands/import_apply.py` | Использовать `runtime.executor`, мета/статы из runtime |
| `connector/delivery/commands/cache_refresh.py` | Использовать `runtime.reader` |

### Инварианты

1. **Delivery не импортирует** `AnkeyApiClient`, `ApiError` и другие target-конкретные классы.
2. `check_api` делает проверку доступности **только через** `TargetRuntime.check()`.
3. Доменные usecase-слои продолжают зависеть **только от доменных портов** (`RequestExecutorProtocol`, `TargetPagedReaderProtocol`), без знания про TargetRuntime.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ unit: `TargetRuntime.check()` возвращает `TargetCheckResult` для ok/fail сценариев
- ✅ unit: `TargetKernel` валидирует `TargetSpec` и строит операции (fail-fast на несовместимом spec)
- ✅ e2e: команды `check_api`, `import_apply`, `cache_refresh` патчат `build_target_runtime` и не зависят от места импорта клиента

**Метрики успеха**:
- Команды не содержат импортов `connector.infra.http.ankey_client` и не вызывают его напрямую.
- Любая замена target-инфры требует изменения только target-slice (а не команд).

---

## 📐 Диаграммы

Будут добавлены после стабилизации интерфейса `TargetRuntime` и выделения `TargetSpec/Kernel/Gateway/Driver`.

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- На первом шаге dataset ApplyAdapter может всё ещё формировать `RequestSpec` (endpoint knowledge не полностью вынесен).
- `TargetSpec` для Ankey описывает только необходимые операции, а не весь внешний API.

**Риски**:
- ⚠️ Риск: избыточная абстракция (слишком много сущностей) → **Митигация**: держать Spec/Kernel минимальными, покрывать только реально используемые операции.
- ⚠️ Риск: расхождение “операций” между dataset и target-spec → **Митигация**: вводить операции постепенно и покрывать контракт тестами на соответствие.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/cli/bootstrap.py` | Упрощение wiring | Ввести `build_target_runtime` |
| `commands/check_api.py` | Станет target-agnostic | Перейти на `runtime.check()` |
| `commands/import_apply.py` | Инъекция executor через runtime | Использовать `runtime.executor` |
| `commands/cache_refresh.py` | Инъекция reader через runtime | Использовать `runtime.reader` |
| `domain/usecases/*` | Нет | Порты не меняются |

---

## 📚 Документация

**Обновлена документация**:
- ⏳ `docs/dev/layers/target/target-runtime.md` — описание TargetRuntime и границ ответственности
- ⏳ UML диаграммы target-slice (после стабилизации)

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md) — решаемая проблема
- [docs/dev](../dev/README.md) — дев-документация проекта (в процессе)
- [ADR-INDEX](../INDEX.md) — индекс ADR

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено на основе обсуждения очистки load-слоя |
| 2026-02-13 | Зафиксированы границы: TargetRuntime = infra-артефакт, доменные порты не меняем |
