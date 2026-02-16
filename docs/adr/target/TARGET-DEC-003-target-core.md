# TARGET-DEC-003: Target слой — plugin-core TargetCore, TargetSpec/OperationSpec и инструменты реализации (консолидировано)

> **Статус**: Принято  
> **Дата**: 2026-02-16  
> **Решает проблему**: [TARGET-PROBLEM-003](./TARGET-PROBLEM-003-target-core.md)  
> **Связанный DEC**: [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) — частично superseded этим решением  
> **Участники решения**: @xorex-LC

---

## 📌 Коротко (что фиксируем)

Осевая модель Target слоя:

1) **TargetCore = plugin-core** (agnostic механики + фасад + kernel)  
2) **TargetInfra Providers = плагины** (driver + spec + нюансы)  
3) **Policy**: механизм в core, правила в spec

В рамках v1 дополнительно фиксируем:

- минимальный стабильный набор `FaultKind` и `RetryDirective` — **берём текущие из кода** и закрепляем семантику;
- вводим `OperationSpec` сразу (v1), определяем назначение и размещение (типы в core, каталог операций в provider spec);
- определяем контракт `meta()/stats()` и принцип интеграции с существующими diagnostics/report (без дублей);
- утверждаем инструменты (зависимости) TargetCore v1 и правила интеграции внешних библиотек (без “мини‑фреймворка”).

### Что закрывает этап 0

- документ `TARGET-DEC-003` становится каноничным для TargetCore и переводится в статус `Принято`;
- фиксируется связь: `TARGET-DEC-003` **частично supersede** `TARGET-DEC-001`;
- фиксируется окно обратной совместимости для Ankey с режимом по умолчанию `auto`;
- фиксируется явная точка удаления legacy в финальном cleanup этапе.

### Что именно частично supersede из TARGET-DEC-001

- модель расширения Target слоя через `TargetProvider`/registry;
- разграничение `mechanism in core` vs `rules in spec`;
- эволюция от transport-bound request к `OperationSpec`/alias;
- policy совместимости (`core/auto/legacy`) на период миграции.

### Что остаётся валидным из TARGET-DEC-001

- идея `TargetRuntime` как единой точки входа;
- typed boundary-модели (`TargetMeta`, `TargetStats`, `TargetCheckResult`);
- базовый принцип single-attempt driver + retry-owner в target-slice.

---

## 📋 Контекст

Мы строим Target слой как единую точку доступа к sink/target-системе (API/DB/File/ES/…), при этом:

- usecase’ы и домен **не знают** о транспорте/протоколах/исключениях драйверов;
- target-специфика описывается через **TargetSpec** (с перспективой DSL);
- добавление нового target-типа выполняется как подключение **плагина** (provider), без переписывания core;
- избегаем “мини‑фреймворка” внутри приложения: commodity-механики (HTTP-клиент, retry/backoff, валидация спеки, structured logging, plugin discovery) берём из battle-tested libs и изолируем внутри target-slice.

---

## ✅ Решение

### 1) Зона ответственности TargetCore (строго)

**TargetCore делает (обязан):**
- предоставляет **единый фасад** `TargetRuntime` (executor/reader/check/meta/stats);
- валидирует и “компилирует” TargetSpec: `TargetKernel -> CompiledTargetSpec`;
- реализует agnostic механики:
  - retry/backoff/jitter (механизм),
  - нормализацию ошибок в единый `FaultKind/ExecutionResult`,
  - safe logging + redaction,
  - (опционально) rate limiting / circuit breaker как механизмы (если появится необходимость);
- предоставляет **registry/factory** для подключения providers (ручной реестр v1; discovery позже при необходимости).

**TargetCore не делает (запреты):**
- не содержит эндпоинтов/SQL/индексов/таблиц и прочих деталей конкретного target;
- не импортирует HTTP/DB/ES библиотеки;
- не содержит dataset-специфики (mapping/payload schema);
- не является хранилищем секретов (может использовать SecretProvider на apply, но не хранит секреты).

---

### 2) TargetInfra Providers (плагины)

**Provider содержит:**
- реализацию `TargetDriver` (REST/DB/File/ES);
- TargetSpec (каталог операций + правила retry/error/redaction/paging) для данного target-типа;
- нюансы транспорта: auth, pagination mapping, response parsing.

**Provider не содержит:**
- общие механики (retry engine, нормализация ошибок, redaction pipeline) — это в core.

---

### 3) Policy: механизм vs правила

- **Механизм** (как выполнять retry/backoff/logging/normalization) — в TargetCore engines.
- **Правила** (когда ретраить, какие ошибки к чему маппить, что редактировать) — в TargetSpec конкретного provider.

---

## 🧱 Состав модулей TargetCore (минимум v1)

> Логический состав. Точная раскладка по файлам может отличаться, но назначение сохраняется.

### Контракты и модели
- `contracts.py`  
  Протоколы/интерфейсы (наружу): `TargetRuntime`, `RequestExecutor`, `TargetPagedReader`, `TargetProvider` (контракт плагина), `TargetDriver` (контракт драйвера), `SecretProvider`.
- `models.py`  
  Стабильные DTO: `ExecutionResult`, `FaultKind`, `RetryDirective`, `RequestIntent`, `RequestSpec`, `TargetMeta`, `TargetStats`, диагностические структуры.

### Спека и kernel
- `spec_models.py`  
  Типы TargetSpec/OperationSpec/RetryPolicySpec/ErrorMapSpec/RedactionSpec/PagingSpec (v1: минимум под API kind).
- `kernel.py`  
  Валидация + компиляция спеки: строит `CompiledTargetSpec`, резолверы операций, предикаты правил, подготовленные redaction-правила.

### Engines (механики)
- `engines/retry_engine.py`  
  Механизм повторов: backoff+jitter, лимиты попыток, выполнение retry directives по правилам compiled-spec.
- `engines/error_normalizer.py`  
  Нормализация driver errors/response → `FaultKind` (+ reason, retryable, retry_after).
- `engines/safe_logging.py`  
  Safe view request/response + redaction по compiled-spec.

### Facade и подключение плагинов
- `runtime.py`  
  `TargetRuntime` facade: выдаёт порты (executor/reader), реализует check/meta/stats, гарантирует “no raw exceptions”.
- `registry.py`  
  Ручная регистрация providers (`target_type -> provider`) + сборка runtime.
- `plugins.py` *(опционально)*  
  discovery providers через entry points (включать только по необходимости).

---

## 📦 Контракты v1: `FaultKind` и `RetryDirective` (утверждено)

### FaultKind (минимальный стабильный набор v1)

Оставляем существующий набор из кода (`TargetFaultKind`) и фиксируем смысл:

- `SPEC` — ошибка спеки/настройки/нашей конфигурации (невалидная операция, конфликт правил, missing capability).
- `AUTH` — аутентификация (типично 401).
- `PERMISSION` — права (типично 403).
- `DATA` — неверный запрос/данные (400/422 и аналоги).
- `NOT_FOUND` — не найдено (404 и аналоги).
- `CONFLICT` — конфликт состояния (409 и аналоги).
- `THROTTLE` — лимиты/квоты (429 и аналоги; возможен `Retry-After`).
- `TRANSIENT` — временная ошибка/сеть/сервер (5xx, timeouts, connection reset).
- `UNKNOWN` — прочее/не классифицировано.

### RetryDirective (минимальный стабильный набор v1)

Оставляем существующий набор из кода (`RetryDirective`) и фиксируем смысл:

- `NO_RETRY` — завершить попытки, вернуть failure.
- `RETRY_BACKOFF` — повторить с backoff+jitter (механизм core).
- `RETRY_AFTER` — повторить, уважая `Retry-After` (если есть), иначе fallback на backoff.
- `ESCALATE` — поднять на уровень выше (stop-fast/фатальная ошибка операции).

#### Mutate + retry (case `resourceexists`)
Не вводим новый `RetryDirective`.  
В v1 добавляем в правила ретрая **опциональный `mutation` hook** (например `mutation="regenerate_id"`), который core выполнит перед следующей попыткой. Конкретная мутация — **правило в spec** конкретного provider.

---

## 🧩 OperationSpec (v1): назначение, границы, размещение (утверждено)

### Что такое OperationSpec
`OperationSpec` — декларативное описание **операции target по alias**, чтобы dataset/usecase говорили к примеру “выполни `users.upsert`”, не зная URL/таблиц/индексов.

### Зачем он нужен
- развязывает dataset-binding от транспорта;
- позволяет на уровне операции задавать дефолты (timeout/success criteria/retry profile/redaction overrides);
- является естественным мостом к будущему DSL (каталог операций — самый устойчивый элемент).

### Где лежат сами операции (op data)
- **Типы (`OperationSpec`, `HttpOperationData`, …)** — в TargetCore (`spec_models.py`).
- **Каталог операций (`alias -> OperationSpec`)** — в TargetSpec конкретного provider (TargetInfra Provider).
  - v1: фиксируем в provider набор операций для **API kind** (HTTP), как первую реализацию.
  - В будущем другие providers (DB/File/ES) смогут использовать тот же alias, но со своими `OperationSpec(kind=...)`.

### Минимальный состав OperationSpec v1 (API kind)
- `alias`
- `kind="http"`
- `timeout_ms` (опционально)
- `expected_statuses` (или success criteria)
- `retry_profile` (опционально) / overrides
- `redaction_override` (опционально)
- `http`: `{method, path_template, query_defaults, header_defaults}`

---

## 📊 `meta()/stats()` (v1): объём и интеграция без дублей (утверждено)

### Принцип v1
**Не создаём вторую систему отчётности.**  
`TargetRuntime.meta()/stats()` являются источником технического контекста и счётчиков; они пробрасываются в существующий `ReportCollector.context` (через существующие presenter’ы), без новых сущностей.

### Meta (статичное “что за target”)
Минимум v1:
- `target_type`
- `transport` (http/db/file/…)
- `endpoint/base_url` или `dsn` (masked/safe)
- `capabilities`
- `provider_name` (если есть)
- `spec_version` (если есть)

### Stats (счётчики за run)
Опираемся на текущий `TargetStats` в коде (requests/retries/failures).  
Дополнения допускаются только если **не дублируют** отчётные слои:
- latency (sum/max/last) — можно добавить позже при необходимости;
- breakdown по fault kind — опционально и только если это не конфликтует с diagnostic layer.

---

## 🧰 Инструменты реализации (v1) и правила интеграции зависимостей

### Принципы интеграции внешних библиотек (чтобы не делать “мини‑фреймворк”)

1. **Внешние библиотеки импортируются только в target-slice (infra)**: core engines/spec validation/logging и provider drivers.  
   Домен и usecase слой видят только порты/DTO/результаты.
2. **Обязательные зависимости — минимальны**, “тяжёлые” опции включаются как extras.
3. Любая библиотека оборачивается тонким адаптером/фасадом так, чтобы:
   - наружу выходили только *наши* типы (ExecutionResult/FaultKind/…),
   - исключения библиотек не пересекали границы слоя.

### Выбор библиотек (v1)

**TargetCore (обязательные):**
- **Pydantic v2** (+ `pydantic-settings` при необходимости) — spec models/validation.
- **Tenacity** — retry/backoff engine (через обёртку RetryEngine, чтобы типы tenacity не утекали наружу).
- **structlog** — structured logging + redaction processors (через SafeLogger).

**TargetInfra Providers (пример: REST):**
- **HTTPX** — HTTP-клиент для REST targets (sync + async, pooling).  
  (HTTPX — не зависимость core, а зависимость REST provider’а.)

**Опциональные (extras):**
- **OpenTelemetry** — трассировка/метрики/логи (observability) для runtime/driver.
- **SQLAlchemy** — DB targets (если/когда добавим DB драйверы).
- **importlib.metadata entry points** — discovery target-провайдеров при росте количества target-типов.
- **limits** (rate limiting), **pybreaker** (circuit breaker) — только если появится реальная потребность.

---

## 🔌 Точки расширения (куда добавлять реализации)

- Новый target-type: **в provider** (driver + spec + нюансы) + регистрация в `registry`.
- Новая операция/эндпоинт: **в provider spec** (каталог операций).
- Новые retry/error/redaction правила: **в provider spec**.
- Новый механизм (engine): **в TargetCore**, но только если это реально agnostic и полезно нескольким target-типам.

---

## 🗂️ Пример структуры каталогов/модулей (v1)

> Это **референс-скелет**, чтобы одинаково понимать границы TargetCore vs Providers.  
> Точная интеграция с текущим репозиторием может отличаться по именам файлов, но роли модулей — те же.

```text
connector/infra/target/
  core/
    contracts.py
    models.py
    spec_models.py        # TargetSpec + OperationSpec(kind+data) + retry/redaction rules (agnostic)
    kernel.py             # validate + compile via transport registry
    runtime.py            # facade: uses compiled_spec + engines + driver
    registry.py           # providers registry
    engines/
      retry_engine.py     # tenacity wrapper
      safe_logging.py     # structlog processors
      mutations.py        # optional: apply mutation hooks
  transports/
    http/
      op_models.py        # HttpOperationData (pydantic)
      compiler.py         # compile OperationSpec.data -> CompiledHttpOperation
      request_builder.py  # intent + compiled op -> HttpRequest
      normalizer.py       # httpx response/exception -> ExecutionResult (FaultKind, Retry-After)
      paging.py           # paging helpers (optional)
      driver_base.py      # optional small base around httpx
  providers/
    ankey_rest/
      spec.py             # TargetSpec + operations catalog (kind="http", data={...})
      driver.py           # AnkeyRestDriver (httpx) OR wrapper around existing AnkeyApiClient
      provider.py         # register provider, load_spec, build_driver, mutations()
      payloads/
        users.py          # provider-owned payload mapping для users.upsert
      mutations.py        # regenerate_id etc (ankey-specific)
```

### Правило импортов (anti-leak)
- `core/*` **не импортирует** `httpx/requests`, `sqlalchemy`, `elasticsearch`, и т.п.
- `providers/*/driver.py` **может импортировать** transport libs (например `httpx`)
- `core/engines/*` **может импортировать** `tenacity`, `structlog`, `pydantic`
- домен/usecase слой **не импортирует** ничего из transport libs, tenacity/structlog/pydantic-settings

---

## 🧩 Примеры кода (минимальные, v1)

> Примеры ниже показывают “скелет” контрактов и wiring.  
> Это не попытка сделать фреймворк, а фиксация того, **что именно означает TargetCore как plugin-core**.

### 1) Контракты TargetCore (contracts.py)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Mapping, Any

# ---- core DTO (упрощённо) ----

@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    status: int | None = None
    fault_kind: str | None = None
    reason: str | None = None
    retry_after_s: float | None = None
    details: Mapping[str, Any] | None = None


class TargetDriver(Protocol):
    # Контракт драйвера провайдера:
    # - делает одну попытку I/O
    # - не содержит retry/backoff
    # - может выбрасывать driver-specific исключения (они будут нормализованы в core)
    def execute_once(self, request: "RequestSpec") -> "DriverResponse": ...
    def read_page_once(self, request: "PageRequest") -> "DriverPageResponse": ...
    def close(self) -> None: ...


class TargetProvider(Protocol):
    # Контракт плагина:
    # - отдаёт TargetSpec (каталог операций + правила)
    # - строит TargetDriver
    target_type: str
    def load_spec(self) -> "TargetSpec": ...
    def build_driver(self, settings: Mapping[str, Any]) -> TargetDriver: ...


class TargetRuntime(Protocol):
    def execute(self, intent: "RequestIntent") -> ExecutionResult: ...
    def read_page(self, intent: "PageIntent") -> "TargetPage": ...
    def check(self) -> ExecutionResult: ...
    def meta(self) -> Mapping[str, Any]: ...
    def stats(self) -> Mapping[str, Any]: ...
```

---

### 2) OperationSpec и TargetSpec (spec_models.py, pydantic)

```python
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal, Mapping, Any

class HttpOperationData(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    query_defaults: Mapping[str, str] = Field(default_factory=dict)
    header_defaults: Mapping[str, str] = Field(default_factory=dict)

class OperationSpec(BaseModel):
    alias: str
    kind: Literal["http"] = "http"
    timeout_ms: int | None = None
    expected_statuses: set[int] = Field(default_factory=set)
    retry_profile: str | None = None
    redaction_override: Mapping[str, Any] | None = None
    http: HttpOperationData

class RetryRuleSpec(BaseModel):
    # match по fault_kind/status/reason -> directive (+ optional mutation)
    fault_kind: str | None = None
    status: int | None = None
    reason: str | None = None

    directive: Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]
    mutation: str | None = None  # mutate+retry (например "regenerate_id")

class TargetSpec(BaseModel):
    target_type: str
    transport: Literal["http"] = "http"
    capabilities: set[str] = Field(default_factory=set)

    operations: dict[str, OperationSpec] = Field(default_factory=dict)
    retry_rules: list[RetryRuleSpec] = Field(default_factory=list)

    redaction: Mapping[str, Any] = Field(default_factory=dict)
    error_map: Mapping[str, Any] = Field(default_factory=dict)
```

---

### 3) Kernel: validate + compile (kernel.py)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .spec_models import TargetSpec, OperationSpec, RetryRuleSpec

@dataclass(frozen=True)
class CompiledTargetSpec:
    spec: TargetSpec
    resolve_operation: Callable[[str], OperationSpec]
    match_retry_rule: Callable[[dict], RetryRuleSpec | None]

def validate(spec: TargetSpec) -> None:
    aliases = set()
    for alias, op in spec.operations.items():
        if alias in aliases:
            raise ValueError(f"duplicate operation alias: {alias}")
        aliases.add(alias)
        if op.http.path_template and not op.http.path_template.startswith("/"):
            raise ValueError(f"bad path_template for {alias}: {op.http.path_template}")

def compile_spec(spec: TargetSpec) -> CompiledTargetSpec:
    validate(spec)

    def resolve_operation(alias: str) -> OperationSpec:
        try:
            return spec.operations[alias]
        except KeyError:
            raise ValueError(f"unknown operation alias: {alias}")

    def match_retry_rule(ctx: dict) -> RetryRuleSpec | None:
        for rule in spec.retry_rules:
            if rule.fault_kind and rule.fault_kind != ctx.get("fault_kind"):
                continue
            if rule.status and rule.status != ctx.get("status"):
                continue
            if rule.reason and rule.reason != ctx.get("reason"):
                continue
            return rule
        return None

    return CompiledTargetSpec(spec=spec, resolve_operation=resolve_operation, match_retry_rule=match_retry_rule)
```

---

### 4) RetryEngine (tenacity wrapper) — механизм в core, правила в spec (engines/retry_engine.py)

```python
from __future__ import annotations

from dataclasses import dataclass
from tenacity import Retrying, stop_after_attempt, wait_exponential_jitter

@dataclass
class RetryConfig:
    max_attempts: int = 5
    base: float = 0.2
    max_wait: float = 10.0

class RetryEngine:
    def __init__(self, cfg: RetryConfig):
        self._cfg = cfg

    def iter_attempts(self):
        return Retrying(
            stop=stop_after_attempt(self._cfg.max_attempts),
            wait=wait_exponential_jitter(initial=self._cfg.base, max=self._cfg.max_wait),
            reraise=False,
        )
```

---

### 5) Runtime: фасад, который связывает driver + compiled_spec + engines (runtime.py)

```python
from __future__ import annotations

from .kernel import CompiledTargetSpec
from .models import ExecutionResult

class CoreTargetRuntime:
    def __init__(
        self,
        *,
        driver,
        compiled: CompiledTargetSpec,
        retry_engine,
        normalizer,
        safe_logger,
        mutations=None,
    ):
        self._driver = driver
        self._compiled = compiled
        self._retry = retry_engine
        self._norm = normalizer
        self._log = safe_logger
        self._mutations = mutations or {}
        self._stats = {"requests_total": 0, "retries_total": 0, "failures_total": 0}

    def execute(self, intent) -> ExecutionResult:
        op = self._compiled.resolve_operation(intent.alias)
        request = intent.to_request(op)

        last_result: ExecutionResult | None = None

        for attempt in self._retry.iter_attempts():
            with attempt:
                self._stats["requests_total"] += 1
                try:
                    raw = self._driver.execute_once(request)  # одна попытка I/O
                    result = self._norm.from_response(raw)
                except Exception as e:
                    result = self._norm.from_exception(e)

                last_result = result
                if result.ok:
                    return result

                ctx = {"fault_kind": result.fault_kind, "status": result.status, "reason": result.reason}
                rule = self._compiled.match_retry_rule(ctx)
                if not rule or rule.directive in ("NO_RETRY", "ESCALATE"):
                    self._stats["failures_total"] += 1
                    return result

                self._stats["retries_total"] += 1

                if rule.mutation:
                    mut = self._mutations.get(rule.mutation)
                    if mut:
                        request = mut(request)  # mutate request before retry

        self._stats["failures_total"] += 1
        return last_result or ExecutionResult(ok=False, fault_kind="UNKNOWN")

    def meta(self) -> dict:
        return {
            "target_type": self._compiled.spec.target_type,
            "transport": self._compiled.spec.transport,
            "capabilities": sorted(self._compiled.spec.capabilities),
        }

    def stats(self) -> dict:
        return dict(self._stats)
```

---

### 6) Provider: Ankey REST — каталог операций + правила + driver (providers/ankey_rest/*)

```python
# providers/ankey_rest/spec.py
from __future__ import annotations

from connector.infra.target.core.spec_models import TargetSpec, OperationSpec, HttpOperationData, RetryRuleSpec

def build_ankey_spec() -> TargetSpec:
    spec = TargetSpec(target_type="ankey", transport="http", capabilities={"apply", "read"})
    spec.operations = {
        "health.check": OperationSpec(
            alias="health.check",
            http=HttpOperationData(method="GET", path_template="/ankey/health"),
            expected_statuses={200},
        ),
        "users.upsert": OperationSpec(
            alias="users.upsert",
            http=HttpOperationData(
                method="PUT",
                path_template="/ankey/managed/user/{target_id}",
                query_defaults={"decrypt": "false"},
            ),
            expected_statuses={200, 201},
        ),
    }
    spec.retry_rules = [
        RetryRuleSpec(fault_kind="THROTTLE", directive="RETRY_AFTER"),
        RetryRuleSpec(fault_kind="TRANSIENT", directive="RETRY_BACKOFF"),
        RetryRuleSpec(fault_kind="CONFLICT", reason="resourceexists", directive="RETRY_BACKOFF", mutation="regenerate_id"),
    ]
    spec.redaction = {"headers": ["Authorization"], "json_fields": ["password"]}
    return spec
```

```python
# providers/ankey_rest/driver.py
from __future__ import annotations

import httpx

class AnkeyRestDriver:
    def __init__(self, client: httpx.Client):
        self._client = client

    def execute_once(self, request):
        return self._client.request(
            request.method,
            request.url,
            headers=request.headers,
            params=request.query,
            json=request.json,
            timeout=request.timeout_s,
        )
```

---

## 🧭 Как сохранить обратную совместимость для Ankey (пока миграция идёт)

Фиксируем режимы совместимости:

- `core` — использовать только новый TargetCore runtime без fallback.
- `auto` — **режим по умолчанию**: сначала TargetCore runtime, при неподдерживаемом кейсе допускается controlled fallback в legacy.
- `legacy` — принудительно использовать legacy runtime (только как временный аварийный режим).

Правила окна совместимости:

- legacy разрешён до финального cleanup этапа, но каждое использование должно быть явно помечено как `legacy`;
- fallback в `auto` должен писать warning и контекст в отчёт/логи (`target_runtime_mode`, `target_runtime_fallback_reason`);
- весь новый target-код добавляется только в `infra/target/core` и provider-модули, без расширения legacy-пути;
- критерий завершения окна: паритет `check/read/apply` по поведению и диагностике на Ankey без fallback.

---

## 🧪 Проверка (DoD v1)

- usecase/dataset слои не импортируют transport libs / retry/logging libs;
- наружу из runtime не выходят raw exceptions транспорта;
- `FaultKind`/`RetryDirective` имеют единые значения и используются в отчётах/диагностике;
- `OperationSpec` есть, каталог операций задаётся в provider spec;
- `meta()/stats()` прокинуты в report context без создания новой системы отчётности.

### DoD этапа 0 (зафиксировано этим ADR)

- устранён дрейф идентификаторов ADR (`PROBLEM-003`/`DEC-003`) и ссылок между документами;
- в явном виде зафиксирован partial supersede `DEC-001 <- DEC-003`;
- в явном виде зафиксирован compatibility policy (`core/auto/legacy`, default=`auto`);
- определена точка удаления legacy: финальный cleanup этап roadmap.

### Backlog этапа 1 (закрыт)

- выделить `TargetProvider` контракт и ручной registry в target-slice;
- перенести Ankey wiring в provider-модуль без прямого знания Ankey в factory;
- оставить совместимость с legacy через режим `auto`, но запретить развитие legacy-функционала;
- расширить architecture tests на запрет новых импортов legacy target wiring в delivery-командах.

### DoD этапа 3 (закрыт)

- `TargetSpec`/`OperationSpec` переведены на `pydantic`-модели (`immutable + forbid extra`);
- retry-механизм выделен в отдельный engine на базе `tenacity` (через внутреннюю обёртку);
- safe logging/redaction выделены в engine c `structlog`-адаптером и без утечки raw payload наружу;
- добавлены architecture-guards на границы импортов `tenacity/structlog/pydantic_settings`;
- unit/e2e тесты и performance-bench scaffolding синхронизированы под pydantic-spec API (`model_copy`).

### Готовность к этапу 4 (закрыт prep)

- primary-реализации engines размещены в `infra/target/core/engines/*`; root `infra/target/engines/*` оставлены как compatibility wrappers;
- payload mapping для `users.upsert` перенесён в provider-слой (`providers/ankey_rest/payloads/users.py`);
- `datasets/employees/load/user_payload.py` оставлен как legacy-обёртка в миграционном контексте (без собственной бизнес-логики).

### Этап 4: что удаляем (legacy cleanup checklist)

Удаляем полностью (директории/файлы):
- `connector/infra/target/legacy/__init__.py`
- `connector/infra/target/legacy/runtime.py`
- `connector/infra/target/legacy/ankey_paged_reader.py`
- `connector/infra/target/ankey_gateway.py`
- `connector/infra/target/providers/ankey/__init__.py`
- `connector/infra/target/providers/ankey/provider.py`

Удаляем compatibility wrappers (оставляем только `core/*` как primary API):
- `connector/infra/target/factory.py`
- `connector/infra/target/runtime.py`
- `connector/infra/target/gateway.py`
- `connector/infra/target/kernel.py`
- `connector/infra/target/models.py`
- `connector/infra/target/spec.py`
- `connector/infra/target/spec_ankey.py`
- `connector/infra/target/engines/__init__.py`
- `connector/infra/target/engines/retry_engine.py`
- `connector/infra/target/engines/error_normalizer.py`
- `connector/infra/target/engines/safe_logging.py`

Удаляем legacy-режим и fallback в runtime factory:
- из `core/factory.py` убираем режимы `legacy/auto`, оставляем только `core`;
- из `core/provider.py` и `providers/ankey_rest/provider.py` убираем `build_legacy_runtime(...)`;
- из settings/CLI убираем конфиг `target_runtime_mode=legacy|auto`, оставляем единый core path.

Удаляем legacy-связки в delivery bootstrap:
- `build_api_client`, `build_api_executor`, `build_api_reader` из `connector/delivery/cli/bootstrap.py`;
- прямой импорт `AnkeyTargetPagedReader` из legacy в `connector/delivery/cli/bootstrap.py`.

Удаляем миграционные обёртки в dataset-слое:
- `connector/datasets/employees/load/user_payload.py` (после перевода всех импортов на provider payload builder).

### Следующий этап roadmap

- этап 4: финальный cleanup legacy-ветки после подтверждения паритета без fallback.

---

## 🔗 Связанные документы

- [TARGET-PROBLEM-003](./TARGET-PROBLEM-003-target-core.md) — решаемая проблема
- [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) — базовый DEC (частично superseded)
- [docs/dev](../../dev/target/) — дев-документация проекта (в процессе)
- [ADR INDEX](../INDEX.md) — индекс ADR

---

## 📝 История изменений

| Дата | Событие |
|------|---------|
| 2026-02-16 | Базовая модель TargetRuntime/TargetSpec и фиксация TargetCore как plugin-core |
| 2026-02-16 | Инструменты/идиомы + зона ответственности/модули/контракты |
| 2026-02-16 | Этап 0 закрыт: DEC принят, связи/ID синхронизированы, compatibility policy (`auto`) зафиксирован |
| 2026-02-16 | Этап 3 закрыт: pydantic-spec + tenacity retry engine + structlog safe logging + architecture guards |
| 2026-02-16 | Prep перед этапом 4 закрыт: engines в core + provider-owned payload mapping для users.upsert |
