# TARGET-DEC-001: TargetRuntime + target-spec slice для изоляции load-слоя от target-инфры

> **Статус**: Принято
> **Дата предложения**: 2026-02-13
> **Решает проблему**: [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

В текущей реализации `apply/refresh/check_api` в delivery-слое напрямую “знают” о конкретном target (Ankey IDM): сборка клиента/экзекьютора/ридера и часть target-специфики размазаны по `delivery/cli/bootstrap.py` и командам.

Это приводит к:
- сцеплению delivery ↔ infra-реализациями (и исключениями) target;
- дублированию wiring и политик подключения;
- усложнению тестирования (хрупкий monkeypatch);
- затруднению расширения на другие target-типовые реализации (API/DB/File).

См. [TARGET-PROBLEM-001](./TARGET-PROBLEM-001-load-layer-target-wiring.md).

---

## 🎯 Решение

1) Ввести **TargetRuntime** как **infra-артефакт** (не доменный порт) — единую точку доступа к инструментам target-системы (API/DB/File) для delivery-команд.

2) За TargetRuntime держать **строгую target-specific спецификацию** (в духе cache слоя):
- `TargetSpec`: описывает поддерживаемые операции/эндпоинты/ожидаемые статусы/ошибки/нюансы сервера;
- `TargetKernel`: валидирует/нормализует спецификацию и предоставляет “операции” в удобном виде.

3) Взаимодействие с target выполнять через **gateway/driver**:
- `TargetDriver` (transport): отвечает за низкоуровневый I/O (HTTP/DB/File, auth, ssl, timeouts) и делает **одну транспортную попытку**;
- `TargetGateway`: переводит потребности приложения в операции target, используя `TargetKernel` и `TargetDriver`, и является **единственным владельцем retry-политики**.

4) Доменные порты **не менять**:
- `apply` (usecase) продолжает работать через `RequestExecutorProtocol`/`TargetPagedReaderProtocol`.
- `TargetRuntime` предоставляет реализации этих портов наружу (delivery/usecases), скрывая конкретный target.

5) `check_api` переводится на `TargetRuntime.check()` — delivery больше не импортирует `ApiError` и не знает “какой endpoint пинговать”.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули** (infra):
- `TargetRuntime` в `connector/infra/target/runtime.py`
  - `TargetRuntime` как `Protocol` (граница зависимости)
  - `DefaultTargetRuntime` как стандартная production-реализация
  - `executor: RequestExecutorProtocol`
  - `reader: TargetPagedReaderProtocol | None`
  - `check(): TargetCheckResult`
  - `meta(): TargetMeta`, `stats(): TargetStats`, `reset()`
- `TargetMeta/TargetStats` в `connector/infra/target/models.py`
- `TargetSpec` в `connector/infra/target/spec/*.py` (пока код-спека, позже — декларативно)
- `TargetKernel` в `connector/infra/target/kernel.py`
- `TargetGateway` в `connector/infra/target/gateway.py`
- `TargetDriver` (transport, single-attempt) в `connector/infra/target/driver/*.py`

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
from typing import Literal, Protocol

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPagedReaderProtocol

TargetFaultKind = Literal[
    "SPEC",
    "AUTH",
    "PERMISSION",
    "DATA",
    "NOT_FOUND",
    "CONFLICT",
    "THROTTLE",
    "TRANSIENT",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class TargetMeta:
    target_type: str
    base_url: str | None = None
    transport: str = "http"


@dataclass(frozen=True, slots=True)
class TargetStats:
    requests_total: int = 0
    retries_total: int = 0
    failures_total: int = 0


@dataclass(frozen=True, slots=True)
class TargetCheckResult:
    ok: bool
    latency_ms: int | None = None
    fault_kind: TargetFaultKind | None = None
    error_code: SystemErrorCode | None = None
    error_message: str | None = None


class TargetRuntime(Protocol):
    executor: RequestExecutorProtocol
    reader: TargetPagedReaderProtocol | None

    def reset(self) -> None: ...
    def stats(self) -> TargetStats: ...
    def meta(self) -> TargetMeta: ...
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


### Матрица взаимодействий с target (AS-IS → TO-BE)

Цель матрицы — **жёстко зафиксировать**, какие слои касаются target и **как именно**. После внедрения `TargetRuntime` точка контакта для delivery становится единственной, а usecase-слой остаётся на доменных портах.

| Слой \ Операция | APPLY | CACHE_REFRESH | CHECK_API |
|---|---|---|---|
| **Delivery** (`connector/delivery/*`) | **AS-IS:** команды собирают `AnkeyApiClient/AnkeyRequestExecutor`, управляют retry/reset, берут `retries_used`, формируют target-context для отчёта.  **TO-BE:** команды получают `TargetRuntime`, используют `runtime.executor` и `runtime.meta()/stats()`. | **AS-IS:** команды собирают reader и управляют retry/reset на клиенте. **TO-BE:** команды используют `runtime.reader` и `runtime.meta()/stats()`, не знают реализацию reader/driver. | **AS-IS:** команда напрямую пингует target endpoint и ловит `ApiError`. **TO-BE:** команда вызывает `runtime.check()`, а метод/endpoint проверки описан в `TargetSpec`. |
| **Usecases** (`connector/usecases/*`) | **AS-IS:** apply-usecase уже зависит от `RequestExecutorProtocol` (ок). **TO-BE:** без изменений портов; улучшение качества диагностик (не терять `record_ref`). | **AS-IS:** зависит от `TargetPagedReaderProtocol`, но местами есть утечки infra (логирование/интроспекция реализаций). **TO-BE:** usecase не импортирует infra и не “лезет” в `reader.client`; нужные метрики/контекст приходят через runtime или нейтральный контракт. | **AS-IS:** логика в delivery. **TO-BE:** остаётся в delivery, но через `runtime.check()` (отдельный usecase необязателен). |
| **Datasets** (`connector/datasets/*`) | **AS-IS:** ApplyAdapter формирует `RequestSpec` и может содержать endpoint-knowledge. **TO-BE:** на шаге 1 допускается сохранить это, но рекомендуется перейти к **endpoint alias** (`"users.upsert"`) вместо сырого пути; алиасы резолвятся через `TargetSpec` внутри target-slice. | **AS-IS:** refresh-адаптеры задают `list_path`/mapping. **TO-BE:** аналогично — предпочтительны alias (`"users.list"`, `"orgs.list"`), чтобы не множить dataset×target знание. | — |
| **Infra** (`connector/infra/*`) | **AS-IS:** `infra/http/*` + `request_executor` реализуют транспорт и адаптер доменного порта. **TO-BE:** всё собирается внутри target-slice через runtime/factory; общие политики (retry/error/redaction) централизованы. | **AS-IS:** `infra/target/*` реализует reader. **TO-BE:** reader выдаётся runtime; политика ошибок/ретраев унифицирована. | **AS-IS:** target-check реализован в delivery. **TO-BE:** target-check реализован в target-slice (spec/kernel/driver), наружу — только `TargetCheckResult`. |

**Инвариант после миграции**: usecase-слой зависит только от доменных портов, delivery зависит от `TargetRuntime`, а весь target-hardcode (endpoint’ы, правила retry, классификация ошибок, safe-logging) лежит в `TargetSpec`/target-slice.


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

### Уточнения для принятия (Decision Clarifications)

1. `TargetRuntime` фиксируется как `Protocol` + `DefaultTargetRuntime` (production owner поведения).
2. `meta()/stats()` возвращают строго типизированные модели (`TargetMeta`, `TargetStats`), а не `dict[str, Any]`.
3. `TargetCheckResult` включает `fault_kind` для единой наблюдаемости с apply/refresh.
4. Retry-механика имеет одного владельца: `TargetGateway`; `TargetDriver` не выполняет policy-retry.
5. `TargetSpec` разделяет `fault_rules` (классификация) и `retry_rules` (реакция).
6. Вводится migration kill-switch: `TARGET_RUNTIME_ENABLED=true|false` для безопасного отката.
7. Добавляются архитектурные тесты на границы импортов в `delivery`/`usecases`.
8. Миграция на endpoint alias идёт по этапам с Definition of Done (см. ниже).

---
---

## 🧩 TargetSpec v1 (кодовая спецификация)

> На первом шаге `TargetSpec` **хардкожен в Python**, но спроектирован так, чтобы позже его можно было получать из DSL без изменения `TargetRuntime`.

### Цели TargetSpec

- держать **всю target-специфику** (эндпоинты/таблицы/пагинация/особые статусы/лимиты);
- задавать правила **классификации ошибок** и **retry-политики**;
- задавать правила **безопасного логирования и редактирования (redaction)**.

### Минимальный состав TargetSpec

**Обязательные поля:**
- `target_type`: идентификатор реализации (`ankey`, `postgres`, `files`, `es`, …).
- `capabilities`: поддерживаемые операции (`check`, `execute`, `read_paged`, …).
- `connection`: target-специфичная модель подключения (URL/DSN/path, auth mode, tls/ssl).
- `health_check`: как выполнять `runtime.check()` (описание операции + ожидания).
- `paging`: стратегия пагинации для `read_paged` (offset/limit, cursor/token, search_after/scroll и т.п.).
- `fault_rules`: правила классификации ошибок (HTTP status / исключения драйвера → `FaultKind`).
- `retry_rules`: правила реакции на ошибку (`RetryCondition` → `RetryDirective`).
- `redaction`: правила маскирования для логов (заголовки/поля payload/ответа).

**Nice-to-have (добавлять по мере необходимости):**
- `rate_limits`: лимиты/квоты и поведение при 429.
- `timeouts`: разные таймауты для `check/read/execute`.
- `idempotency`: особенности идемпотентности операций (важно для retry).

---

## 🧭 Классификация ошибок target + retry policy

### Зачем

Нужно, чтобы delivery/usecases не знали про HTTP/DB/IO исключения, а получали единообразный результат:
- что произошло (класс сбоя),
- можно ли ретраить,
- как это отразить в диагностике (severity и system_code).

Рекомендованный подход: **не ретраить всё подряд** — ретраи полезны только для transient/лимитов, иначе это превращается в “retry storm”.

### Ось A: FaultKind (природа сбоя)

Минимальный набор категорий (универсально для REST/DB/File/ES):

- `SPEC`: ошибка спецификации/конфигурации (`TargetSpec` несовместим или некорректен).
- `AUTH`: аутентификация (неверные креды/токен/сертификат).
- `PERMISSION`: авторизация (прав нет).
- `DATA`: ошибка данных/запроса (валидация, constraint violation, 400/422).
- `NOT_FOUND`: ресурс/endpoint/row отсутствует (404 / missing row).
- `CONFLICT`: конфликт состояния (409 / unique violation).
- `THROTTLE`: rate limit/quota (429).
- `TRANSIENT`: временная недоступность/сеть/таймаут/5xx.
- `UNKNOWN`: всё, что не попало в классификацию (в strict-режиме должно иметь диагностический код).

### Ось B: RetryPolicy (реакция)

- `NO_RETRY`: исправлять данные/креды/спеку, ретраи не помогут.
- `RETRY_BACKOFF`: экспоненциальный backoff + jitter, ограничение по попыткам.
- `RETRY_AFTER`: уважать `Retry-After` (если target возвращает).
- `ESCALATE`: прекратить операцию/пачку, если превышен порог (например, слишком много 401 или 5xx подряд).

### Базовые правила для HTTP (если target = REST)

- `401` → `AUTH` + `NO_RETRY`
- `403` → `PERMISSION` + `NO_RETRY`
- `400/422` → `DATA` + `NO_RETRY`
- `404` → `NOT_FOUND` + `NO_RETRY` *(если это не “eventual consistency”, тогда это фиксируется в TargetSpec как исключение)*
- `409` → `CONFLICT` + `NO_RETRY` *(или отдельная доменная стратегия, но не blind retry)*
- `429` → `THROTTLE` + `RETRY_AFTER` (если есть) иначе `RETRY_BACKOFF`
- `500/502/503/504` + сетевые ошибки/таймауты → `TRANSIENT` + `RETRY_BACKOFF`

### Severity и диагностика

Рекомендуемая базовая схема:
- `TRANSIENT/THROTTLE` → обычно `warning` (если успешно восстановились), иначе `error` по исчерпанию попыток.
- `AUTH/PERMISSION/SPEC/DATA` → `error` сразу (no-retry).

### Правила ретрая: условие + директива

`RetryPolicy` — **общая механика** в target-slice (кол-во попыток, backoff, jitter, уважение `Retry-After`).  
`TargetSpec.retry_rules` задаёт **условия**, при которых ретрай допустим, и **директиву**, что именно делать.

### Владелец retry-механики (single owner)

- `TargetGateway`:
  - применяет `retry_rules`;
  - выполняет `RETRY_BACKOFF/RETRY_AFTER/MUTATE_AND_RETRY`;
  - учитывает лимиты и публикует `retries_total`.
- `TargetDriver`:
  - выполняет одну I/O попытку;
  - нормализует транспортную ошибку в форму, пригодную для `fault_rules`;
  - не содержит policy-retry (чтобы не было двойного ретрая).

**Минимальный набор условий (RetryCondition):**
- `http_status` — ретрай по статусу (например `429`, `503`, `504`).
- `fault_kind` — ретрай по нормализованной категории (например `TRANSIENT`, `THROTTLE`).
- `custom_rule` — target-специфичный матч по причине/коду ошибки (например, vendor error code).

**Минимальный набор директив (RetryDirective):**
- `NO_RETRY`
- `RETRY_BACKOFF` (экспоненциальный backoff + jitter, с лимитами по попыткам)
- `RETRY_AFTER` (если `Retry-After` доступен)
- *(опционально)* `MUTATE_AND_RETRY` — ретрай с изменением запроса по target-правилу (см. пример ниже)

> Рекомендация: для фоновых операций использовать экспоненциальный backoff с jitter; это снижает риск “retry storm”.

#### Пример target-специфичного правила (Ankey: `resourceexists`)

Для Ankey конфликт `resourceexists` на `CREATE` — это условие для **контролируемого ретрая**:  
1) сгенерировать новый `target_id` (или иной идентификатор в соответствии с target-правилом);  
2) выполнить `RETRY_BACKOFF` по общему механизму.

Важно: правило “когда ретраить” и “как мутировать запрос” описывается в `TargetSpec` и исполняется в target-slice, чтобы dataset-слой не содержал API-специфику.

---

## 🧼 Безопасное логирование target (safe logging + redaction)

### Проблема

Target-интеграции почти всегда несут чувствительные данные:
- в **headers** (Authorization, cookies, API keys),
- в **payload** (секреты, PII),
- в **ошибках** (иногда target отражает часть запроса в тексте ошибки).

Если логировать “как есть”, то утечки происходят через логи/репорты/трейсы, где доступ обычно шире, чем к секрет-хранилищу.

### Решение

1) **TargetRuntime (через общий TargetRedactor внутри target-slice) — единственная policy-точка**, где формируется “вид для логов” (`safe view`) запросов/ответов.
2) `TargetSpec.redaction` определяет:
   - список заголовков “запрещено логировать” (по умолчанию: `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`),
   - список полей payload/response, которые маскируются (например `password`, `token`, `secret`, …),
   - режим логирования body (например: `none | keys_only | truncated`).
3) Команды и usecases **никогда** не логируют raw-request/raw-response напрямую — только метаданные и safe view из runtime.

### Инварианты для логов

- В логах/отчётах не должно появляться:
  - сырого `Authorization`/cookie/api-key,
  - секретных полей payload,
  - полных тел ответов (только безопасные выжимки).

> Примечание: правила redaction — часть TargetSpec, чтобы их можно было позже описать декларативно в DSL вместе с остальной target-спецификой.



## 🔐 Secrets в пайплайне и apply (plan meta + hydration через SecretProvider)

### Инварианты

- **Значения секретов** (например `password`) уходят в vault на этапе `enrich` и **дальше по конвейеру не передаются**.
- Дальше по пайплайну передаётся только **мета**, что поле является секретным и будет нужно на `apply`.
- `PlanItem.secret_fields` содержит **только имена секретных полей**, а не значения.
- На этапе `apply` секреты извлекаются **только через** `SecretProvider` (по `record_ref`/ключу и имени поля) и используются лишь для сборки payload.

### Границы ответственности

- **Dataset-layer** не должен “доставать” секреты и не должен знать про хранилище секретов.  
  Dataset указывает, *какие* поля считаются секретными (в SinkSpec/правилах), но не работает с их значениями.
- **Apply usecase / target-slice** отвечает за hydration секретов перед выполнением операции (и за корректную диагностику, если секрет отсутствует).

### Следствия для `connector/datasets/*/load`

После перехода на `TargetRuntime + TargetSpec` и использования действующего `SinkSpec`:
- ручные payload-builder’ы и логика “дотягивания секретов” в `datasets/*/load` становятся дубликатами/утечками ответственности;
- пакет `datasets/employees/load` должен быть **минимизирован** (до dataset-binding/alias) или **удалён** после переноса:
  - сборки payload на общий builder по `SinkSpec`,
  - операций/эндпоинтов/параметров — в `TargetSpec.operations`,
  - retry/конфликт-стратегий — в `TargetSpec.fault_rules`/retry rules.

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/target/runtime.py` | Новый `TargetRuntime` (инфра-артефакт) |
| `connector/infra/target/models.py` | Typed модели `TargetMeta`, `TargetStats`, `TargetCheckResult` |
| `connector/infra/target/spec/*` | `TargetSpec` для Ankey (код-спека) |
| `connector/infra/target/kernel.py` | `TargetKernel` (валидация/нормализация спеки) |
| `connector/infra/target/gateway.py` | `TargetGateway` (перевод операций в driver calls) |
| `connector/infra/target/driver/*` | `TargetDriver` (transport: http/db/file, single-attempt) |
| `connector/delivery/cli/bootstrap.py` | Заменить `build_api_*` на `build_target_runtime` |
| `connector/delivery/commands/check_api.py` | Использовать `runtime.check()` вместо прямого клиента |
| `connector/delivery/commands/import_apply.py` | Использовать `runtime.executor`, мета/статы из runtime |
| `connector/delivery/commands/cache_refresh.py` | Использовать `runtime.reader` |
| `tests/architecture/test_target_layer_boundaries.py` | Границы импортов delivery/usecases относительно target-инфры |
| `tests/performance/target/*` | pyperf benchmark-набор для runtime/kernel/gateway/redaction |

### Этапы миграции + Definition of Done

1. **Stage 0: runtime skeleton + kill-switch**
   - DoD:
     - добавлены `TargetRuntime` (`Protocol`) и `DefaultTargetRuntime`;
     - `TARGET_RUNTIME_ENABLED` переключает старый/новый wiring в `bootstrap`.
2. **Stage 1: delivery wiring**
   - DoD:
     - `import_apply`, `cache_refresh`, `check_api` получают runtime через `build_target_runtime`;
     - команды не создают `AnkeyApiClient` напрямую.
3. **Stage 2: fault/retry/redaction centralization**
   - DoD:
     - retry удалён из delivery/usecases и живёт только в gateway;
     - `fault_rules` + `retry_rules` покрыты unit-тестами;
     - safe logging идёт только через runtime.
4. **Stage 3: endpoint alias rollout**
   - DoD:
     - `RequestSpec` и refresh-spec используют alias (`users.upsert`, `users.list`, ...);
     - резолв alias выполняется через `TargetKernel`.
5. **Stage 4: legacy cleanup**
   - DoD:
     - удалены legacy wiring-функции `build_api_*`;
     - удалены неиспользуемые части `datasets/*/load`, дублирующие target-логику.

### Инварианты

1. **Delivery не импортирует** `AnkeyApiClient`, `ApiError` и другие target-конкретные классы.
2. `check_api` делает проверку доступности **только через** `TargetRuntime.check()`.
3. Доменные usecase-слои продолжают зависеть **только от доменных портов** (`RequestExecutorProtocol`, `TargetPagedReaderProtocol`), без знания про TargetRuntime.
4. `meta()/stats()` возвращают typed-модели (`TargetMeta`, `TargetStats`), а не dictionary-контракт.
5. Любые ошибки транспорта/драйвера нормализуются в рамках target-slice (`fault_rules` + `retry_rules`), наружу исключения не “протекают”.
6. Ретраи выполняются **только** в `TargetGateway`; базовое правило — только для `TRANSIENT/THROTTLE` по `TargetSpec.retry_rules`, а исключения (например `CONFLICT` + `MUTATE_AND_RETRY`) допускаются только при явном target-правиле.
7. `TargetDriver` делает ровно одну попытку и не содержит policy-retry.
8. Логи формируются только через `TargetRuntime` safe view; raw headers/payload не логируются.
9. План содержит только `secret_fields` (имена), а значения секретов извлекаются на `apply` через `SecretProvider` и не попадают в логи/артефакты.

### Паттерны и Python-идиомы реализации

#### Архитектурные паттерны

- **Facade**: `TargetRuntime` скрывает детали `kernel/gateway/driver` и даёт стабильный API для delivery.
- **Factory**: `build_target_runtime(...)` — единая точка сборки runtime и зависимостей.
- **Gateway + Adapter**: `TargetGateway` переводит domain intent в target операции, `TargetDriver` адаптирует транспорт.
- **Strategy (data-driven)**: `fault_rules` и `retry_rules` задают поведение без `if/elif`-каскадов по коду.
- **Null Object**: если target не поддерживает чтение, отдаём `reader=None` или `NullTargetReader` с явным контрактом.
- **Result Object**: `TargetCheckResult` возвращает структурированный результат вместо протечки transport exceptions.

#### Python-идиомы и правила кода

1. Иммутабельные typed-модели для границ:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetMeta:
    target_type: str
    base_url: str | None = None
    transport: str = "http"
```

2. Контракты через `Protocol`, реализация через composition:

```python
from typing import Protocol


class TargetRuntime(Protocol):
    def meta(self) -> TargetMeta: ...
    def stats(self) -> TargetStats: ...


class DefaultTargetRuntime:
    def __init__(self, gateway: TargetGateway, reader: TargetPagedReaderProtocol | None):
        self._gateway = gateway
        self.reader = reader
```

3. Декоратор для retry/policy-обёртки на gateway-операциях:

```python
from functools import wraps


def with_retry(operation_alias: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            policy = self._kernel.retry_policy(operation_alias)
            return self._retry_engine.run(lambda: fn(self, *args, **kwargs), policy=policy)
        return wrapper
    return deco
```

4. Декоратор для safe logging (только redacted view):

```python
from functools import wraps


def safe_log(event_name: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            result = fn(self, *args, **kwargs)
            self._logger.info(event_name, extra=self._redactor.safe_meta(result))
            return result
        return wrapper
    return deco
```

5. Табличная классификация ошибок вместо разветвлённого `if/elif`:

```python
HTTP_FAULT_MAP = {
    401: "AUTH",
    403: "PERMISSION",
    404: "NOT_FOUND",
    429: "THROTTLE",
    500: "TRANSIENT",
    502: "TRANSIENT",
    503: "TRANSIENT",
    504: "TRANSIENT",
}

fault_kind = HTTP_FAULT_MAP.get(status_code, "UNKNOWN")
```

6. Явные импорты на границе слоёв (анти-утечка инфры):

```python
# good (delivery)
from connector.delivery.cli.bootstrap import build_target_runtime

# bad (delivery forbidden)
# from connector.infra.http.ankey_client import AnkeyApiClient
```

#### Правила применения декораторов

- декораторы применяются в `connector/infra/target/*`, не в `connector/usecases/*`;
- `safe_log` использует общий `TargetRedactor/safe_view` из runtime и не вводит собственные правила маскирования;
- декораторы не должны скрывать доменные исключения: после ретраев наружу возвращается нормализованный результат/ошибка;
- порядок декораторов фиксированный: `retry` -> `redaction/safe-log` -> `metrics`.


### Чистка после миграции (что именно “подчистить”)

**Delivery**:
- удалить прямые импорты/использование target-конкретных классов и исключений (например, `Ankey*`, `ApiError`);
- убрать ручное управление retry/reset и чтение `retries_used` с клиента;
- получать контекст target (`base_url`, `target_type`, `retries_total`) через `runtime.meta()/stats()`.

**Usecases**:
- убрать импорты infra-логирования (`logEvent`) и любые прямые зависимости от `connector.infra.*`;
- убрать интроспекцию реализаций (например, `reader.client.getRetryAttempts()`); метрики должны приходить через runtime или нейтральный контракт;
- улучшить качество диагностик: везде, где возможно, прокидывать `record_ref` в ошибки.

**Datasets**:
- (рекомендуемо) перейти на **endpoint alias** в `RequestSpec`/refresh-spec вместо “сырого пути” — чтобы не множить знание о target по датасетам.

**Infra / target-slice**:
- сконцентрировать target-инфру в `connector/infra/target/*` (factory/runtime/spec/kernel/driver/gateway);
- транспорт (`http/db/file`) остаётся внутренней деталью target-slice и не импортируется извне.

**Проверки по репозиторию** (сигналы “граница не выдержана”):
- в `connector/delivery/**` не должно быть импортов `connector.infra.http.*`, `Ankey*`, `ApiError`;
- в `connector/usecases/**` не должно быть импортов `connector.infra.*`;
- retry/backoff правила не должны дублироваться в командах и usecase-слое.
- в delivery/usecases не должно быть доступа к runtime-данным через “магические ключи” `dict`, только через typed-поля.


---

## 🧪 Валидация решения

**Тесты**:
- ✅ unit: `TargetRuntime.check()` возвращает `TargetCheckResult` для ok/fail сценариев
- ✅ unit: `TargetKernel` валидирует `TargetSpec` и строит операции (fail-fast на несовместимом spec)
- ✅ unit: `fault_rules` корректно маппят ошибки/статусы в `FaultKind`, а `retry_rules` — в `RetryDirective` (включая `Retry-After`).
- ✅ unit: `redaction` гарантирует отсутствие чувствительных заголовков/полей в safe-логах (Authorization/cookie/api-key/secret fields).
- ✅ e2e: команды `check_api`, `import_apply`, `cache_refresh` патчат `build_target_runtime` и не зависят от места импорта клиента
- ✅ architecture: `connector/delivery/**` не импортирует `connector.infra.http.*`/`Ankey*`; `connector/usecases/**` не импортирует `connector.infra.*`
- ✅ unit: `check()` возвращает `fault_kind` для fail-сценариев и не протекает transport-exception наружу

**Метрики успеха**:
- Команды не содержат импортов `connector.infra.http.ankey_client` и не вызывают его напрямую.
- Любая замена target-инфры требует изменения только target-slice (а не команд).

---

## ⏱️ Benchmark-набор для покрытия реализации

Набор ориентирован на micro-bench/regression в стиле `tests/performance/apply/*` (pyperf + `--fast` режим).

### Сценарии benchmark (минимум для DEC-001)

| Сценарий | Файл | Что меряем | Критерий приемки |
|---|---|---|---|
| Runtime execute overhead (happy path) | `tests/performance/target/bench_target_runtime_execute_overhead.py` | overhead `DefaultTargetRuntime.executor` относительно прямого вызова executor на N item | регрессия не хуже `+15%` к зафиксированному baseline |
| Runtime check path | `tests/performance/target/bench_target_runtime_check.py` | стоимость `runtime.check()` (ok/fail) со stub-driver | регрессия не хуже `+15%` к baseline, стабильный stddev |
| Gateway retry engine | `tests/performance/target/bench_target_gateway_retry_transient.py` | стоимость policy-retry (`TRANSIENT`, `THROTTLE`) и no-retry ветки | no-retry path не деградирует > `+10%` |
| Kernel operation resolve | `tests/performance/target/bench_target_kernel_operation_lookup.py` | lookup alias (`users.upsert`, `users.list`) и валидация cache hit | регрессия не хуже `+10%` |
| Redaction safe view | `tests/performance/target/bench_target_redaction_safe_view.py` | redaction headers/payload (малый/средний/большой payload) | регрессия не хуже `+15%`, без утечек секретных ключей |

### Smoke-check benchmark entrypoints

- `tests/performance/target/test_bench_target_runtime.py`:
  - проверяет, что каждый benchmark-скрипт запускается в `--fast` режиме без падений;
  - повторяет паттерн из `tests/performance/apply/test_bench_apply.py`.

### Команды запуска

```bash
pytest tests/performance/target/test_bench_target_runtime.py -m performance -q
.venv/bin/python tests/performance/target/bench_target_runtime_execute_overhead.py --fast
.venv/bin/python tests/performance/target/bench_target_gateway_retry_transient.py --fast
```

### Benchmark DoD для DEC-001

1. Все benchmark entrypoint'ы проходят smoke-тест.
2. Для каждого сценария зафиксирован baseline (артефакт CI или файл в `tests/performance/target/baselines/`).
3. PR считается регрессионным при превышении порогов из таблицы.
4. В benchmark отчётах не присутствуют секретные данные (проверка safe view/redaction).

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
- [docs/dev](../../dev/README.md) — дев-документация проекта (в процессе)
- [ADR INDEX](../INDEX.md) — индекс ADR

---

## 🔎 Источники и обоснования (коротко)

- Рекомендации по обработке transient faults (retry + backoff + jitter): Microsoft Well-Architected.
- Практика exponential backoff + jitter: AWS Architecture Blog и AWS Builders’ Library.
- Семантика HTTP и `Retry-After`: RFC 9110.
- Рекомендации по безопасному логированию и исключению утечек через логи: OWASP Logging Cheat Sheet.

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено на основе обсуждения очистки load-слоя |
| 2026-02-13 | Зафиксированы границы: TargetRuntime = infra-артефакт, доменные порты не меняем |
| 2026-02-15 | Дополнено: TargetSpec v1, классификация ошибок/retries и правила safe logging/redaction |
| 2026-02-15 | Уточнены: `Protocol + DefaultTargetRuntime`, typed `meta/stats`, single-owner retry, staged migration, benchmark-набор |
| 2026-02-15 | Добавлено: паттерны реализации и Python-идиомы (decorators, Protocol, data-driven rules, import boundaries) |
| 2026-02-15 | Выровнена внутренняя согласованность: retry-исключения, `meta/stats` поля, safe-logging policy-point |
