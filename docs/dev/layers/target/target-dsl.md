# Target DSL — декларативная спецификация целевой системы

> **Назначение**: YAML-файл спецификации полностью управляет поведением TargetKernel.
> Никакого Python-хардкода для классификации ошибок, политики повторов, маскирования логов
> и каталога операций — всё объявляется декларативно.

---

## Содержание

- [1. Роль DSL в архитектуре слоя](#1-роль-dsl-в-архитектуре-слоя)
- [2. Иерархия моделей спецификации](#2-иерархия-моделей-спецификации)
- [3. TargetCapability](#3-targetcapability)
- [4. FaultRule — правило классификации ошибки](#4-faultrule--правило-классификации-ошибки)
- [5. RetryRule — правило повторной попытки](#5-retryrule--правило-повторной-попытки)
- [6. RetryConfig — параметры повторных попыток](#6-retryconfig--параметры-повторных-попыток)
- [7. OperationSpec — спецификация операции](#7-operationspec--спецификация-операции)
- [8. RedactionSpec — безопасное логирование](#8-redactionspec--безопасное-логирование)
- [9. HealthSpec](#9-healthspec)
- [10. TargetSpec — корневая модель](#10-targetspec--корневая-модель)
- [11. Загрузчик: load_target_spec()](#11-загрузчик-load_target_spec)
- [12. Регистрация в registry.yml](#12-регистрация-в-registryyml)
- [13. Аннотированный YAML-пример](#13-аннотированный-yaml-пример)
- [14. Pydantic v2 coercion — что важно знать](#14-pydantic-v2-coercion--что-важно-знать)
- [15. Инварианты и ошибки валидации](#15-инварианты-и-ошибки-валидации)
- [16. FAQ](#16-faq)
- [17. Тесты](#17-тесты)

---

## 1. Роль DSL в архитектуре слоя

### Принцип declarative-first

Target DSL реализует принцип «поведение целевой системы описывается данными, а не кодом».
Всё, что TargetKernel должен знать об Ankey IDM (или любом другом провайдере), хранится
в одном YAML-файле. Python-код ядра остаётся провайдеро-нейтральным.

Что остаётся в Python (не переносится в YAML):

- **auth** — адаптеры `httpx.Auth` (Bearer, Basic, mTLS);
- **paging strategy** — алгоритм итерации по страницам ответа;
- **mutations** — Python-функции, зарегистрированные в `TargetMutationRegistry`;
- **provider wiring** — сборка `TargetRuntime` в `AnkeyTargetProvider`.

Что YAML контролирует полностью:

| Аспект поведения           | Секция YAML       |
|----------------------------|-------------------|
| Возможности провайдера     | `capabilities`    |
| Классификация HTTP-ошибок  | `fault_rules`     |
| Политика повторных попыток | `retry_rules`     |
| Параметры backoff          | `retry_config`    |
| Маскирование в логах       | `redaction`       |
| Health-check операция      | `health`          |
| Каталог операций           | `operations`      |

### Жизненный цикл спецификации

Спецификация читается один раз при запуске провайдера и остаётся неизменяемой
(frozen Pydantic models) на протяжении всего runtime. Никакого hot-reload не предусмотрено:
изменение YAML требует перезапуска.

```
datasets/registry.yml
        |
        | targets.ankey --> "targets/ankey.target.yaml"
        v
datasets/targets/ankey.target.yaml
        |
        v
load_target_spec("ankey")          # connector/domain/target_dsl/loader.py
        |
        | 1. load_registry()
        | 2. read_yaml(path)
        | 3. _inject_aliases()
        | 4. TargetSpec.model_validate()
        v
TargetSpec  (frozen Pydantic model)
        |
        v
TargetKernel.__init__(spec, compiler_registry)
        |
        | строит lookup-таблицы O(1)
        | компилирует операции
        v
TargetKernel  (неизменяемый на весь runtime)
        |
        v
TargetGateway / DefaultTargetRuntime
```

### Место в кодовой базе

```
connector/
├── domain/
│   └── target_dsl/
│       ├── __init__.py          # публичное API: load_target_spec
│       ├── loader.py            # загрузчик: registry -> YAML -> TargetSpec
│       └── spec_models.py       # Pydantic-модели спецификации
├── infra/
│   └── target/
│       ├── core/
│       │   ├── kernel.py        # TargetKernel: classify_fault, retry, redact
│       │   └── spec_models.py   # реэкспорт моделей для infra-слоя
│       └── providers/
│           └── ankey_rest/
│               └── provider.py  # AnkeyTargetProvider.build_core_runtime()
└── datasets/
    ├── registry.yml             # targets: ankey -> targets/ankey.target.yaml
    └── targets/
        └── ankey.target.yaml    # конкретная спецификация
```

---

## 2. Иерархия моделей спецификации

Все модели наследуют от `_SpecModel` — базового класса с двумя директивами Pydantic:

- `extra="forbid"` — неизвестные поля в YAML вызывают ошибку валидации;
- `frozen=True` — экземпляры неизменяемы после создания (hashable, thread-safe).

```
TargetSpec
├── target_type: str
├── capabilities: frozenset[TargetCapability]
├── fault_rules: tuple[FaultRule, ...]
│   └── FaultRule
│       ├── fault_kind: TargetFaultKind
│       ├── match_status: int | None
│       ├── match_status_range: tuple[int, int] | None
│       └── match_error_code: str | None
├── retry_rules: tuple[RetryRule, ...]
│   └── RetryRule
│       ├── directive: RetryDirective
│       ├── match_fault: TargetFaultKind | None
│       ├── match_status: int | None
│       ├── match_reason: str | None          (нормализуется к lowercase)
│       └── mutation: str | None
├── retry_config: RetryConfig
│   ├── max_attempts: int           (default: 3)
│   ├── backoff_base: float         (default: 0.5)
│   ├── backoff_max: float          (default: 30.0)
│   └── jitter: bool                (default: True)
├── redaction: RedactionSpec
│   ├── forbidden_metadata_keys: frozenset[str]
│   ├── forbidden_fields: frozenset[str]
│   └── body_mode: "none" | "keys_only" | "truncated"
├── health: HealthSpec
│   └── operation_alias: str        (default: "health.check")
└── operations: dict[str, OperationSpec]
    └── OperationSpec
        ├── alias: str              (auto-injected из ключа словаря)
        ├── kind: str               (default: "http")
        ├── expected_statuses: tuple[int, ...]  (default: (200,))
        ├── timeout_ms: int | None
        ├── retry_profile: str | None
        ├── redaction_override: dict[str, Any] | None
        └── data: dict[str, Any]   (opaque transport payload)
```

Типы-перечисления (объявлены как `Literal` в Python):

```python
TargetFaultKind = Literal[
    "SPEC", "AUTH", "PERMISSION", "DATA",
    "NOT_FOUND", "CONFLICT", "THROTTLE", "TRANSIENT", "UNKNOWN",
]

TargetCapability = Literal["check", "execute", "read_paged"]

RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]
```

---

## 3. TargetCapability

### Перечень значений

| Значение     | Что разрешает                                              |
|--------------|------------------------------------------------------------|
| `check`      | Выполнение health-check (обязательно при наличии `health`) |
| `execute`    | Запись: upsert, create, update, delete                     |
| `read_paged` | Чтение с пагинацией (list, search)                         |

### Декларация в YAML

```yaml
capabilities:
  - check
  - execute
  - read_paged
```

YAML-список автоматически преобразуется в `frozenset[TargetCapability]` при валидации Pydantic.

### Проверка в TargetKernel

TargetKernel предоставляет два метода для работы с capabilities:

```python
def has_capability(self, capability: TargetCapability) -> bool:
    """Проверить, поддерживает ли target заданную capability."""
    return capability in self._capabilities

def require_capability(self, capability: TargetCapability) -> None:
    """Проверить обязательную capability и поднять ошибку при отсутствии."""
    if not self.has_capability(capability):
        raise ValueError(
            f"target capability {capability!r} is not supported "
            f"by target_type={self._spec.target_type!r}",
        )
```

`require_capability` вызывается перед каждой операцией в gateway/driver, чтобы
провайдер с ограниченным набором capabilities не мог случайно выполнить запрещённую
операцию. Например, провайдер только для записи, у которого нет `read_paged`,
выбросит ошибку при попытке вызвать list-операцию.

### Инвариант здоровья

Наличие секции `health` в спецификации автоматически требует capability `check`.
Это проверяется в `TargetSpec._validate_spec_integrity()` на уровне модели — см.
[раздел 10](#10-targetspec--корневая-модель).

---

## 4. FaultRule — правило классификации ошибки

### Назначение

FaultRule отображает HTTP-статус или error_code драйвера на логический `TargetFaultKind`.
Классификация выполняется TargetKernel без знания о конкретном провайдере.

### Поля модели

```python
class FaultRule(_SpecModel):
    fault_kind: TargetFaultKind           # к какому виду относить ошибку
    match_status: int | None = None       # точный HTTP-статус (например, 404)
    match_status_range: tuple[int, int] | None = None  # диапазон [low, high]
    match_error_code: str | None = None   # строковый код от драйвера (например, "NETWORK_ERROR")
```

### Правило: ровно один matcher

FaultRule обязан иметь **ровно один** активный matcher. Допустимые комбинации:

- только `match_status` — точный код;
- только `match_status_range` — включительный диапазон `[low, high]`;
- только `match_error_code` — строковый код от транспортного драйвера.

Нельзя одновременно использовать `match_status` и `match_status_range`. Правило без
ни одного matcher не проходит валидацию.

```python
# ВЕРНО: точный статус
FaultRule(fault_kind="AUTH", match_status=401)

# ВЕРНО: диапазон
FaultRule(fault_kind="TRANSIENT", match_status_range=(500, 599))

# ВЕРНО: код ошибки
FaultRule(fault_kind="TRANSIENT", match_error_code="NETWORK_ERROR")

# ОШИБКА: нет matcher
FaultRule(fault_kind="DATA")
# -> ValueError: fault rule requires match_status, match_status_range or match_error_code

# ОШИБКА: два matcher
FaultRule(fault_kind="DATA", match_status=400, match_status_range=(400, 499))
# -> ValueError: fault rule cannot define both match_status and match_status_range
```

### Перечень TargetFaultKind

| FaultKind     | Семантика                                    | Типичный HTTP-код    |
|---------------|----------------------------------------------|----------------------|
| `SPEC`        | Ошибка конфигурации или спецификации         | нет (internal)       |
| `AUTH`        | Аутентификация отклонена                     | 401                  |
| `PERMISSION`  | Недостаточно прав доступа                    | 403                  |
| `DATA`        | Некорректные данные запроса                  | 400, 422             |
| `NOT_FOUND`   | Ресурс не найден                             | 404                  |
| `CONFLICT`    | Конфликт на стороне сервера                  | 409                  |
| `THROTTLE`    | Превышен лимит частоты запросов              | 429                  |
| `TRANSIENT`   | Временная ошибка (сеть, сервер недоступен)   | 500-599, сеть        |
| `UNKNOWN`     | Не совпало ни одно правило                   | любой неизвестный    |

Значение `UNKNOWN` возвращается автоматически из `classify_fault()`, если ни одно
правило не сматчилось. Это безопасный fallback — нет исключения, есть диагностика.

### Как TargetKernel строит lookup-таблицы

При инициализации TargetKernel разбирает `spec.fault_rules` и собирает три структуры:

```python
# O(1) lookup по точному статусу
self._fault_by_status: dict[int, TargetFaultKind] = {
    r.match_status: r.fault_kind
    for r in spec.fault_rules
    if r.match_status is not None
}

# Линейный список диапазонов (обычно один-два диапазона, например 500-599)
self._fault_by_range: list[tuple[int, int, TargetFaultKind]] = [
    (*r.match_status_range, r.fault_kind)
    for r in spec.fault_rules
    if r.match_status_range is not None
]

# O(1) lookup по строковому коду
self._fault_by_code: dict[str, TargetFaultKind] = {
    r.match_error_code: r.fault_kind
    for r in spec.fault_rules
    if r.match_error_code is not None
}
```

### Приоритет при classify_fault

Метод `TargetKernel.classify_fault()` применяет следующий порядок:

1. Если передан `error_code` и он есть в `_fault_by_code` — возвращает fault_kind по коду.
2. Если передан `status_code` и он есть в `_fault_by_status` — возвращает fault_kind по статусу.
3. Проверяет диапазоны в `_fault_by_range`.
4. Если ничего не совпало — возвращает `"UNKNOWN"`.

`error_code` имеет приоритет над `status_code`. Это позволяет транспортному драйверу
синтезировать коды для событий без HTTP-статуса (например, `NETWORK_ERROR` при разрыве
соединения, когда `status_code=None`).

### FaultKind → SystemErrorCode

TargetKernel переводит `TargetFaultKind` в `SystemErrorCode` для унифицированной
диагностики:

```python
_FAULT_TO_SYSTEM: dict[TargetFaultKind, SystemErrorCode] = {
    "AUTH":       SystemErrorCode.AUTH_UNAUTHORIZED,
    "PERMISSION": SystemErrorCode.AUTH_FORBIDDEN,
    "DATA":       SystemErrorCode.DATA_INVALID,
    "NOT_FOUND":  SystemErrorCode.DATA_INVALID,
    "CONFLICT":   SystemErrorCode.CONFLICT,
    "THROTTLE":   SystemErrorCode.INFRA_UNAVAILABLE,
    "TRANSIENT":  SystemErrorCode.INFRA_UNAVAILABLE,
    "SPEC":       SystemErrorCode.INTERNAL_ERROR,
    "UNKNOWN":    SystemErrorCode.INTERNAL_ERROR,
}
```

---

## 5. RetryRule — правило повторной попытки

### Назначение

RetryRule отображает классифицированную ошибку на директиву повторной попытки.
После того как `classify_fault()` определил `TargetFaultKind`, TargetKernel
вызывает `resolve_retry_action()` для выбора правила.

### Поля модели

```python
class RetryRule(_SpecModel):
    directive: RetryDirective                    # что делать при совпадении
    match_fault: TargetFaultKind | None = None   # фильтр по fault kind
    match_status: int | None = None              # фильтр по HTTP-статусу
    match_reason: str | None = None              # фильтр по причине (нормализуется lowercase)
    mutation: str | None = None                  # имя мутации из TargetMutationRegistry
```

### RetryDirective — что каждое значение означает

| Директива       | Действие                                                                      |
|-----------------|-------------------------------------------------------------------------------|
| `NO_RETRY`      | Не повторять, передать ошибку выше как финальную                              |
| `RETRY_BACKOFF` | Повторить через экспоненциальный backoff (параметры из `retry_config`)        |
| `RETRY_AFTER`   | Повторить с задержкой, указанной в заголовке `Retry-After` от сервера        |
| `ESCALATE`      | Передать ошибку вверх как критическую, не накапливая в retry-счётчике        |

### Правило: хотя бы один matcher

RetryRule обязан содержать хотя бы один из трёх матчеров: `match_fault`,
`match_status`, `match_reason`. Правило без ни одного matcher не проходит валидацию.

```python
# ВЕРНО: только match_fault
RetryRule(directive="RETRY_BACKOFF", match_fault="TRANSIENT")

# ВЕРНО: match_fault + match_reason + mutation
RetryRule(
    directive="RETRY_BACKOFF",
    match_fault="CONFLICT",
    match_reason="resourceexists",
    mutation="regenerate_target_id",
)

# ОШИБКА: нет ни одного matcher
RetryRule(directive="NO_RETRY")
# -> ValueError: retry rule requires match_fault, match_status or match_reason
```

### Нормализация match_reason

Поле `match_reason` автоматически приводится к строчному регистру и обрезается
от пробелов при валидации модели:

```python
@model_validator(mode="after")
def _validate_matcher(self) -> "RetryRule":
    if self.match_reason is not None:
        reason = self.match_reason.strip().lower()
        if reason == "":
            raise ValueError("retry rule match_reason must not be empty")
        object.__setattr__(self, "match_reason", reason)
    ...
```

При сравнении в `resolve_retry_action()` входящий `error_reason` тоже нормализуется:

```python
normalized_reason = error_reason.strip().lower() if isinstance(error_reason, str) else None
```

Таким образом, `match_reason: "resourceexists"` совпадёт и с `"resourceExists"`, и
с `"ResourceExists"` от сервера.

### Опция mutation

`mutation` — строковое имя функции-мутатора, зарегистрированной в
`TargetMutationRegistry`. Мутация применяется перед повторной попыткой.

Например, мутация `regenerate_target_id` генерирует новый UUID перед повтором,
чтобы избежать повторного конфликта `CONFLICT / resourceexists`.

Имя мутации обрезается от пробелов при валидации. Пустая строка не допускается.

```python
rule = RetryRule(
    directive="RETRY_BACKOFF",
    match_reason="resourceexists",
    mutation="regenerate_target_id",
)
assert rule.match_reason == "resourceexists"
assert rule.mutation == "regenerate_target_id"
```

### Порядок правил: first match wins

TargetKernel итерирует `spec.retry_rules` **в порядке объявления** и возвращает
первое совпавшее правило. Более специфичные правила (с несколькими матчерами) должны
идти **перед** более общими:

```yaml
retry_rules:
  # Сначала специфичный случай CONFLICT + reason — RETRY_BACKOFF с мутацией
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id

  # Затем общий случай CONFLICT — NO_RETRY
  - directive: NO_RETRY
    match_fault: CONFLICT
```

Если бы порядок был обратным, специфичное правило никогда не было бы достигнуто.

---

## 6. RetryConfig — параметры повторных попыток

### Поля модели

```python
class RetryConfig(_SpecModel):
    max_attempts: int   = Field(default=3,    ge=0)
    backoff_base: float = Field(default=0.5,  ge=0.0)
    backoff_max:  float = Field(default=30.0, ge=0.0)
    jitter: bool = True
```

### Семантика max_attempts

`max_attempts` — количество **дополнительных** попыток, не считая первоначальной.
Итого выполняется не более `max_attempts + 1` запросов к target.

| max_attempts | Максимум запросов |
|:------------:|:-----------------:|
| 0            | 1 (без повторов)  |
| 1            | 2                 |
| 3 (default)  | 4                 |

### Формула экспоненциального backoff

```
delay(attempt) = min(backoff_base * 2^attempt, backoff_max)
```

При `jitter=True` к задержке добавляется случайное смещение в диапазоне
`[0, delay(attempt)]`, что предотвращает thundering herd при массовых ошибках.

Пример с дефолтными значениями (`backoff_base=0.5`, `backoff_max=30.0`):

| Попытка | Без jitter | С jitter (пример) |
|:-------:|:----------:|:-----------------:|
| 1       | 0.5 с      | 0.3 с             |
| 2       | 1.0 с      | 0.8 с             |
| 3       | 2.0 с      | 1.7 с             |
| 4       | 4.0 с      | 3.2 с             |
| 5       | 8.0 с      | 5.5 с             |
| 6       | 16.0 с     | 12.4 с            |
| 7       | 30.0 с     | 22.1 с (cap)      |

### Инвариант: backoff_max >= backoff_base

```python
@model_validator(mode="after")
def _validate_backoff(self) -> "RetryConfig":
    if self.backoff_max < self.backoff_base:
        raise ValueError("backoff_max must be greater or equal to backoff_base")
    return self
```

### Переопределение из runtime-настроек

`AnkeyTargetProvider` позволяет переопределить параметры retry из конфигурации API
через `apply_retry_overrides()`, не трогая YAML-файл:

```python
def apply_retry_overrides(
    spec: TargetSpec,
    api_settings: ApiSettings,
) -> TargetSpec:
    new_retry_config = spec.retry_config.model_copy(
        update={
            "max_attempts": api_settings.retries,
            "backoff_base": api_settings.retry_backoff_seconds,
        },
    )
    return spec.model_copy(update={"retry_config": new_retry_config})
```

Это единственный легальный способ изменить параметры спецификации на runtime:
YAML задаёт дефолты, а конфигурация приложения (env/config-файл) их перекрывает.

---

## 7. OperationSpec — спецификация операции

### Назначение

OperationSpec декларирует отдельную именованную операцию, которую target-ядро
разрешает по `alias`. Каждая запись в словаре `operations` в YAML — это одна операция.

### Поля модели

```python
class OperationSpec(_SpecModel):
    alias: str                                      # уникальное имя (auto-injected)
    kind: str = "http"                              # тип транспорта
    expected_statuses: tuple[int, ...] = (200,)     # успешные HTTP-статусы
    timeout_ms: int | None = Field(default=None, ge=1)  # таймаут в миллисекундах
    retry_profile: str | None = None                # именованный retry-профиль
    redaction_override: dict[str, Any] | None = None  # переопределение redaction
    data: dict[str, Any] = Field(default_factory=dict)  # opaque транспортный payload
```

### alias: auto-injected из ключа словаря

Поле `alias` является ключом словаря `operations` в YAML. Автор YAML **не должен**
писать `alias` вручную — загрузчик инжектирует его автоматически (см.
[раздел 11](#11-загрузчик-load_target_spec)). Если `alias` не совпадает с ключом,
валидация `TargetSpec` упадёт.

```yaml
# ВЕРНО: alias не указывается, инжектируется из ключа "users.upsert"
operations:
  users.upsert:
    expected_statuses: [200, 201]
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
```

```python
# После загрузки:
spec.operations["users.upsert"].alias  # == "users.upsert"
```

### kind: тип транспорта

По умолчанию `"http"`. Значение `kind` определяет, какой компилятор из
`TransportCompilerRegistry` будет использован для компиляции поля `data` в
`CompiledOperation`. На данный момент поддерживается только `"http"`.

### expected_statuses: допустимые статусы успеха

Кортеж HTTP-статусов, которые считаются успешными для данной операции. Если сервер
вернул код не из этого списка, транспорт классифицирует результат как ошибку и
передаёт его в `classify_fault()`.

```yaml
# Операция upsert ожидает 200 (обновление) или 201 (создание)
users.upsert:
  expected_statuses: [200, 201]
  data: ...
```

### timeout_ms: таймаут операции

Индивидуальный таймаут в миллисекундах. Если `None` — используется глобальный
таймаут HTTP-клиента из конфигурации приложения. Значение должно быть >= 1 мс.

### data: opaque payload для транспорта

Словарь `data` является непрозрачным (opaque) для TargetKernel — ядро его не
интерпретирует и не проверяет структуру. Содержимое целиком передаётся
транспортному компилятору при инициализации.

Для HTTP-транспорта типичная структура `data`:

```yaml
data:
  method: GET                              # HTTP-метод
  path_template: /ankey/managed/user/{target_id}  # шаблон пути с подстановками
  query_defaults:                          # параметры запроса по умолчанию
    _queryFilter: "true"
    _prettyPrint: "false"
```

Инвариант: для `kind="http"` поле `data` не может быть пустым (`{}`) — это вызывает
ошибку валидации:

```python
if self.kind == "http" and not self.data:
    raise ValueError("http operation requires transport payload")
```

### redaction_override

Словарь для переопределения настроек redaction на уровне конкретной операции.
Позволяет одним операциям логировать тело ответа подробнее (например, `body_mode: "keys_only"`),
другим — не логировать совсем (`body_mode: "none"`). Структура словаря соответствует
полям RedactionSpec.

---

## 8. RedactionSpec — безопасное логирование

### Назначение

RedactionSpec определяет правила маскирования чувствительных данных перед записью
в логи. TargetKernel использует эти правила в `redact_headers()` и `safe_body()`.

### Поля модели

```python
class RedactionSpec(_SpecModel):
    forbidden_metadata_keys: frozenset[str] = frozenset({
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-ankey-password",
    })
    forbidden_fields: frozenset[str] = frozenset({
        "password",
        "token",
        "secret",
        "api_key",
    })
    body_mode: Literal["none", "keys_only", "truncated"] = "truncated"
```

### forbidden_metadata_keys

Набор HTTP-заголовков (ключи в нижнем регистре), которые заменяются на `"***"` при
логировании. Сравнение производится через `.lower()` независимо от регистра, в котором
фактически пришёл заголовок.

```python
def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
    forbidden = self._spec.redaction.forbidden_metadata_keys
    return {
        k: ("***" if k.lower() in forbidden else v)
        for k, v in headers.items()
    }
```

Пример: заголовок `"Authorization: Bearer eyJ..."` в логах станет `"Authorization: ***"`.

### forbidden_fields

Набор полей тела запроса/ответа, которые маскируются при логировании payload.
Используется функцией `maskSecretsInObject()` из `connector/common/sanitize.py`.

### body_mode: режим логирования тела

| Значение     | Поведение                                                      |
|--------------|----------------------------------------------------------------|
| `none`       | Тело не логируется совсем, возвращается `None`                 |
| `keys_only`  | Для dict — только список ключей верхнего уровня (без значений) |
| `truncated`  | Первые N символов строки или маскированный dict (дефолт)       |

```python
def safe_body(self, body: Any, redaction: RedactionSpec | None = None) -> Any:
    mode = (redaction or self._spec.redaction).body_mode
    if mode == "none":
        return None
    if isinstance(body, str):
        return truncateText(body)
    if mode == "keys_only" and isinstance(body, dict):
        return list(body.keys())
    return maskSecretsInObject(body)
```

### Дефолтные значения

Все дефолтные значения RedactionSpec — минимально необходимые для безопасного
логирования взаимодействий с REST API. Автор YAML может расширить списки, но
**не сократить** дефолтные значения через YAML (они объявлены как Python-defaults,
а YAML-значение полностью заменяет дефолт при наличии ключа в файле).

---

## 9. HealthSpec

### Назначение

HealthSpec задаёт, какая операция из каталога используется для health-check.
TargetKernel возвращает alias через `health_operation_alias()`.

### Поля модели

```python
class HealthSpec(_SpecModel):
    operation_alias: str = "health.check"
```

### Инварианты

1. `operation_alias` не может быть пустой строкой (проверяется `model_validator`).
2. При создании `TargetSpec` проверяется, что указанный alias присутствует в словаре
   `operations` — иначе валидация упадёт с ошибкой `"health operation alias is not declared"`.
3. Наличие `health` в спецификации требует capability `check` — без неё спецификация
   невалидна.

### YAML-декларация

```yaml
health:
  operation_alias: health.check   # ссылка на ключ в operations
```

Алиас по умолчанию `"health.check"` означает, что в `operations` обязана быть запись
с ключом `health.check`.

---

## 10. TargetSpec — корневая модель

### Поля модели

```python
class TargetSpec(_SpecModel):
    target_type: str
    capabilities: frozenset[TargetCapability]
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    health: HealthSpec
    operations: dict[str, OperationSpec] = Field(default_factory=dict)
```

Поле `operations` — единственное с `default_factory=dict`, все остальные
обязательны для указания в YAML (нет Python-дефолта).

### Валидации на уровне модели

`TargetSpec._validate_spec_integrity()` проверяет три инварианта целостности:

**Инвариант 1**: capability `check` обязательна при наличии `health`:

```python
if "check" not in self.capabilities:
    raise ValueError(
        "health specification requires 'check' capability in target capabilities",
    )
```

**Инвариант 2**: `health.operation_alias` должен быть объявлен в `operations`:

```python
if self.health.operation_alias not in self.operations:
    raise ValueError(
        f"health operation alias is not declared: {self.health.operation_alias!r}",
    )
```

**Инвариант 3**: ключ словаря `operations` должен совпадать с `OperationSpec.alias`
(гарантирует, что alias injection корректно отработал перед валидацией):

```python
for alias, operation in self.operations.items():
    if alias != operation.alias:
        raise ValueError(
            f"operation alias key mismatch: key={alias!r}, alias={operation.alias!r}",
        )
```

### Pydantic v2 coercion при model_validate

При вызове `TargetSpec.model_validate(raw_dict)` Pydantic v2 автоматически
выполняет приведение типов:

- `list` → `tuple[FaultRule, ...]` для `fault_rules` и `retry_rules`;
- `list` → `tuple[int, ...]` для `OperationSpec.expected_statuses`;
- `list` → `frozenset[TargetCapability]` для `capabilities`;
- `list` → `frozenset[str]` для `forbidden_metadata_keys` и `forbidden_fields`;
- `list` → `tuple[int, int]` для `FaultRule.match_status_range`.

Это позволяет писать в YAML обычные списки (`[200, 201]`), получая на выходе
immutable типы Python.

---

## 11. Загрузчик: load_target_spec()

### Публичное API

```python
# connector/domain/target_dsl/__init__.py
from connector.domain.target_dsl.loader import load_target_spec

__all__ = ["load_target_spec"]
```

`load_target_spec` — единственный публичный экспорт модуля `connector.domain.target_dsl`.

### Сигнатура

```python
def load_target_spec(target_type: str) -> TargetSpec:
    """
    Загрузить TargetSpec для указанного провайдера из YAML через registry.

    Аргументы:
        target_type: идентификатор провайдера (ключ в registry.yml -> targets).

    Возвращает:
        Валидированный и неизменяемый TargetSpec.

    Raises:
        DslLoadError: если target_type не найден в registry, файл недоступен
                      или YAML не проходит валидацию TargetSpec.
    """
```

### Алгоритм загрузки: шаг за шагом

```
Шаг 1. load_registry()
        Читает datasets/registry.yml через find_repo_root() + read_yaml().
        Возвращает dict с секциями targets, datasets, cache, dictionaries.

Шаг 2. _resolve_target_path(registry, target_type)
        Ищет registry["targets"][target_type].
        Если ключ отсутствует -> DslLoadError(code="TARGET_DSL_REGISTRY_MISSING")
        Если значение пустое  -> DslLoadError(code="TARGET_DSL_REGISTRY_INVALID")
        Возвращает: find_repo_root() / "datasets" / relative_path

Шаг 3. _read_target_yaml(path, target_type)
        Вызывает read_yaml(path).
        При любой ошибке чтения/парсинга YAML ->
            DslLoadError(code="TARGET_DSL_FILE_ERROR")
        Возвращает raw dict.

Шаг 4. _inject_aliases(raw)
        Для каждого ключа операции в raw["operations"]:
            op_data["alias"] = key
        Модифицирует raw in-place. Не вызывает ошибок.

Шаг 5. _validate_target_spec(raw, target_type, path)
        Вызывает TargetSpec.model_validate(raw).
        Pydantic выполняет:
            - coercion list -> tuple / frozenset
            - field-level валидаторы (FaultRule, RetryRule, OperationSpec, ...)
            - model-level валидатор TargetSpec._validate_spec_integrity()
        При любой Pydantic-ошибке ->
            DslLoadError(code="TARGET_DSL_SPEC_INVALID")
        Возвращает TargetSpec.
```

### Внутренние вспомогательные функции

```python
def _resolve_target_path(registry: dict[str, Any], target_type: str) -> Path:
    """Разрешить путь к YAML-файлу провайдера из registry.yml."""

def _read_target_yaml(path: Path, target_type: str) -> dict[str, Any]:
    """Прочитать YAML-файл провайдера."""

def _inject_aliases(data: dict[str, Any]) -> None:
    """Инжектировать поле alias в каждую операцию из ключа словаря."""

def _validate_target_spec(
    raw: dict[str, Any],
    target_type: str,
    path: Path,
) -> TargetSpec:
    """Валидировать dict как TargetSpec через Pydantic model_validate."""
```

Все функции — приватные (начинаются с `_`). Публичный интерфейс — только
`load_target_spec()`.

### Почему lazy import в AnkeyTargetProvider

`connector/infra/target/providers/ankey_rest/provider.py` импортирует
`load_target_spec` **внутри метода**, а не на уровне модуля:

```python
def build_core_runtime(self, ...) -> TargetRuntime:
    from connector.domain.target_dsl import load_target_spec  # lazy!
    spec = load_target_spec("ankey")
    ...
```

Причина — циклический импорт: `domain.target_dsl` → `domain.dsl` → (косвенно) →
`infra.target`. Lazy import внутри метода разрывает цикл на уровне Python-загрузчика.
Этот паттерн задокументирован в MEMORY как "Circular imports between domain.target_dsl
and infra.target: use lazy import inside method".

### Коды ошибок DslLoadError

| Код                          | Причина                                               |
|------------------------------|-------------------------------------------------------|
| `TARGET_DSL_REGISTRY_MISSING`| `target_type` не найден в секции `targets:` registry  |
| `TARGET_DSL_REGISTRY_INVALID`| Путь в registry пустой или None                       |
| `TARGET_DSL_FILE_ERROR`      | Файл не найден или содержит невалидный YAML           |
| `TARGET_DSL_SPEC_INVALID`    | Pydantic-валидация TargetSpec завершилась с ошибкой   |

`DslLoadError` импортируется из `connector.domain.dsl` — общей DSL-инфраструктуры:

```python
from connector.domain.dsl.issues import DslLoadError
```

---

## 12. Регистрация в registry.yml

### Структура секции targets

```yaml
# datasets/registry.yml
targets:
  ankey: targets/ankey.target.yaml
```

Формат: `<target_type>: <относительный путь от datasets/>`.

Путь разрешается относительно директории `datasets/` в корне репозитория через
`find_repo_root()`. Абсолютный путь: `<repo_root>/datasets/<relative_path>`.

### Пример добавления нового target

1. Создать YAML-файл `datasets/targets/myidm.target.yaml`.
2. Добавить запись в registry:

```yaml
targets:
  ankey: targets/ankey.target.yaml
  myidm: targets/myidm.target.yaml   # новый провайдер
```

3. Загрузить через API:

```python
from connector.domain.target_dsl import load_target_spec

spec = load_target_spec("myidm")
```

4. Создать `AnkeyTargetProvider`-аналог для нового провайдера с вызовом
   `load_target_spec("myidm")` (с lazy import).

Изменение `registry.yml` и создание YAML-файла — единственные шаги для регистрации
нового target. Никакого изменения Python-кода загрузчика не требуется.

---

## 13. Аннотированный YAML-пример

Ниже приведён полный файл `datasets/targets/ankey.target.yaml` с подробными
комментариями к каждой секции.

```yaml
# Декларативная спецификация target-провайдера Ankey IDM REST API.
#
# Загружается через connector.domain.target_dsl.load_target_spec("ankey").
# Что описывается здесь: capabilities, fault_rules, retry_rules, retry_config,
#                         redaction, health, operations.
# Что остаётся в Python:  auth, paging strategy, mutations (функции), wiring.

# Идентификатор провайдера — должен совпадать с ключом в datasets/registry.yml
target_type: ankey

# ---------------------------------------------------------------------------
# Возможности провайдера.
# YAML-список -> frozenset[TargetCapability] при валидации.
# "check"      — разрешён health-check (обязателен при наличии секции health)
# "execute"    — разрешены операции записи (upsert, create, update, delete)
# "read_paged" — разрешено чтение с пагинацией (list, search)
# ---------------------------------------------------------------------------
capabilities:
  - check
  - execute
  - read_paged

# ---------------------------------------------------------------------------
# Health-check конфигурация.
# operation_alias должен совпадать с одним из ключей в sections operations.
# ---------------------------------------------------------------------------
health:
  operation_alias: health.check

# ---------------------------------------------------------------------------
# Классификация ошибок: HTTP-статус / error_code -> FaultKind.
#
# Порядок правил влияет на построение lookup-таблиц, но не на приоритет:
# TargetKernel сначала проверяет error_code, затем точный статус, затем диапазоны.
#
# Каждое правило содержит ровно один matcher:
#   match_status       — точный HTTP-код
#   match_status_range — включительный диапазон [low, high]
#   match_error_code   — строковый код от транспортного драйвера
# ---------------------------------------------------------------------------
fault_rules:
  # 401 — сессия истекла, токен недействителен -> AUTH
  - fault_kind: AUTH
    match_status: 401

  # 403 — прав недостаточно, операция запрещена -> PERMISSION
  - fault_kind: PERMISSION
    match_status: 403

  # 400 — невалидный запрос (поля, формат) -> DATA
  - fault_kind: DATA
    match_status: 400

  # 422 — семантические ошибки валидации Ankey -> DATA
  - fault_kind: DATA
    match_status: 422

  # 404 — ресурс не найден -> NOT_FOUND
  - fault_kind: NOT_FOUND
    match_status: 404

  # 409 — конфликт (ресурс уже существует, версия устарела) -> CONFLICT
  - fault_kind: CONFLICT
    match_status: 409

  # 429 — превышен rate limit Ankey -> THROTTLE
  - fault_kind: THROTTLE
    match_status: 429

  # 5xx — сервер временно недоступен -> TRANSIENT
  # Используем match_status_range для покрытия всего диапазона [500, 599]
  - fault_kind: TRANSIENT
    match_status_range: [500, 599]

  # Сетевые ошибки (таймаут, разрыв соединения) синтезируются драйвером
  # с кодом NETWORK_ERROR (status_code при этом None) -> TRANSIENT
  - fault_kind: TRANSIENT
    match_error_code: NETWORK_ERROR

# ---------------------------------------------------------------------------
# Параметры механики retry: экспоненциальный backoff с jitter.
# max_attempts  — число ДОПОЛНИТЕЛЬНЫХ попыток (не считая первую); итого max 4.
# backoff_base  — начальная задержка в секундах (первый retry ~= 0.5 с)
# backoff_max   — потолок задержки (retry не ждёт дольше 30 с)
# jitter        — рандомизация задержки для предотвращения thundering herd
# ---------------------------------------------------------------------------
retry_config:
  max_attempts: 3
  backoff_base: 0.5
  backoff_max: 30.0
  jitter: true

# ---------------------------------------------------------------------------
# Правила реакции: FaultKind -> RetryDirective.
#
# Порядок критичен: first match wins.
# Более специфичные правила (несколько матчеров) должны идти выше общих.
#
# mutation — имя функции из TargetMutationRegistry; применяется перед повтором.
# match_reason нормализуется к lowercase автоматически при валидации.
# ---------------------------------------------------------------------------
retry_rules:
  # Временные ошибки (5xx, NETWORK_ERROR) — exponential backoff
  - directive: RETRY_BACKOFF
    match_fault: TRANSIENT

  # Rate-limiting — ждать Retry-After из заголовка ответа
  - directive: RETRY_AFTER
    match_fault: THROTTLE

  # Специфичный случай CONFLICT: ресурс уже существует с таким UUID.
  # Мутация генерирует новый target_id и повторяет попытку с другим идентификатором.
  # Это правило должно идти ПЕРЕД общим NO_RETRY для CONFLICT.
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists       # нормализуется к lowercase автоматически
    mutation: regenerate_target_id

  # Остальные fault kinds — финальные, не повторяются
  - directive: NO_RETRY
    match_fault: AUTH

  - directive: NO_RETRY
    match_fault: PERMISSION

  - directive: NO_RETRY
    match_fault: DATA

  - directive: NO_RETRY
    match_fault: NOT_FOUND

  # Общий CONFLICT без специфичного reason — NO_RETRY
  # (специфичный resourceexists уже перехвачен выше)
  - directive: NO_RETRY
    match_fault: CONFLICT

# ---------------------------------------------------------------------------
# Правила маскирования для безопасного логирования.
# Все значения — строки в нижнем регистре.
# YAML-список -> frozenset[str] при валидации.
# ---------------------------------------------------------------------------
redaction:
  # Режим логирования тела ответа:
  # "none"      — тело не логируется совсем
  # "keys_only" — только ключи верхнего уровня dict
  # "truncated" — первые N символов строки или маскированный dict (дефолт)
  body_mode: truncated

  # HTTP-заголовки, которые заменяются на "***" в логах
  forbidden_metadata_keys:
    - authorization
    - cookie
    - set-cookie
    - x-api-key
    - x-ankey-password

  # Поля тела запроса/ответа, которые маскируются в логах
  forbidden_fields:
    - password
    - token
    - secret
    - api_key

# ---------------------------------------------------------------------------
# Каталог операций.
#
# ВАЖНО: alias НЕ указывается в YAML — он инжектируется автоматически
# из ключа словаря загрузчиком (см. _inject_aliases в loader.py).
# kind по умолчанию "http".
# data — опaque payload для транспортного компилятора (ядро не интерпретирует).
#
# Для HTTP-операций:
#   method        — HTTP-метод (GET, PUT, POST, DELETE, PATCH)
#   path_template — шаблон пути; {target_id} заменяется при выполнении
#   query_defaults — параметры строки запроса по умолчанию
#                    (значения ДОЛЖНЫ быть строками, не числами)
# ---------------------------------------------------------------------------
operations:
  # Health-check: минимальный GET для проверки доступности API.
  # page=1 rows=1 — запрашиваем одну запись, чтобы проверить связность
  # без нагрузки на сервер.
  health.check:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/user
      query_defaults:
        page: "1"
        rows: "1"
        _queryFilter: "true"

  # Чтение списка пользователей с пагинацией.
  # _queryFilter=true — обязательный фильтр Ankey API для list-запросов.
  users.list:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/user
      query_defaults:
        _queryFilter: "true"

  # Чтение списка организаций.
  organizations.list:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/organization
      query_defaults:
        _queryFilter: "true"

  # Upsert пользователя: PUT с идентификатором в пути.
  # {target_id} подставляется из PlanItem.target_id при выполнении.
  # expected_statuses: 200 — обновление, 201 — создание нового пользователя.
  # _prettyPrint=true  — Ankey форматирует ответ (полезно для отладки).
  # decrypt=false      — не расшифровывать защищённые поля в ответе.
  users.upsert:
    expected_statuses: [200, 201]
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
      query_defaults:
        _prettyPrint: "true"
        decrypt: "false"
```

---

## 14. Pydantic v2 coercion — что важно знать

### Почему YAML пишем списками

YAML не имеет типа «неизменяемый кортеж» или «неизменяемое множество». Любая
последовательность в YAML — это список. Pydantic v2 автоматически выполняет coercion
при `model_validate()`:

| Python-тип в модели           | YAML-тип      | Coercion          |
|-------------------------------|---------------|-------------------|
| `tuple[FaultRule, ...]`       | `list`        | list → tuple      |
| `tuple[RetryRule, ...]`       | `list`        | list → tuple      |
| `tuple[int, ...]`             | `list`        | list → tuple      |
| `tuple[int, int]`             | `list`        | list → tuple      |
| `frozenset[TargetCapability]` | `list`        | list → frozenset  |
| `frozenset[str]`              | `list`        | list → frozenset  |

### Зачем нужна immutability

- **tuple** для `fault_rules` и `retry_rules` — гарантирует порядок и неизменяемость;
  TargetKernel итерирует их при каждой операции.
- **frozenset** для `capabilities` и `forbidden_*` — обеспечивает O(1) lookup по
  принадлежности (`in`), hashable (frozen model), thread-safe.

### Практический пример

```yaml
capabilities:
  - check
  - execute
  - read_paged
```

После `TargetSpec.model_validate(...)`:

```python
type(spec.capabilities)  # frozenset
spec.capabilities         # frozenset({'check', 'execute', 'read_paged'})

"execute" in spec.capabilities  # True (O(1))
```

```yaml
fault_rules:
  - fault_kind: TRANSIENT
    match_status_range: [500, 599]
```

После валидации:

```python
rule = spec.fault_rules[0]
type(rule.match_status_range)  # tuple
rule.match_status_range        # (500, 599)
```

### Ограничение: extra="forbid"

Все модели используют `extra="forbid"`. Это означает, что любой неизвестный ключ
в YAML вызывает ошибку Pydantic при валидации. Это предотвращает опечатки в именах
полей (например, `match_statuses` вместо `match_status`), которые иначе молча
игнорировались бы.

```yaml
# ОШИБКА: неизвестное поле вызовет DslLoadError
fault_rules:
  - fault_kind: AUTH
    match_statuses: 401   # опечатка! должно быть match_status
```

---

## 15. Инварианты и ошибки валидации

### Таблица проверок

| Инвариант                                    | Где проверяется                   | Исключение         | Как исправить                                         |
|----------------------------------------------|-----------------------------------|--------------------|-------------------------------------------------------|
| FaultRule требует ровно один matcher         | `FaultRule._validate_matcher`     | `ValueError`       | Добавить `match_status`, `match_status_range` или `match_error_code`    |
| FaultRule не может иметь status + range      | `FaultRule._validate_matcher`     | `ValueError`       | Убрать один из двух матчеров                          |
| FaultRule range: low <= high                 | `FaultRule._validate_matcher`     | `ValueError`       | Поменять значения местами                             |
| RetryRule требует хотя бы один matcher       | `RetryRule._validate_matcher`     | `ValueError`       | Добавить `match_fault`, `match_status` или `match_reason`              |
| RetryRule match_reason не пустая строка      | `RetryRule._validate_matcher`     | `ValueError`       | Указать непустое значение или убрать поле             |
| RetryRule mutation не пустая строка          | `RetryRule._validate_matcher`     | `ValueError`       | Указать непустое имя мутации или убрать поле          |
| RetryConfig backoff_max >= backoff_base      | `RetryConfig._validate_backoff`   | `ValueError`       | Увеличить `backoff_max` или уменьшить `backoff_base`  |
| OperationSpec alias не пустая строка         | `OperationSpec._validate_operation` | `ValueError`     | Проверить _inject_aliases — ключ operations не пустой |
| OperationSpec http требует непустой data     | `OperationSpec._validate_operation` | `ValueError`     | Добавить поля method/path_template в `data:`          |
| OperationSpec expected_statuses не пустой   | `OperationSpec._validate_operation` | `ValueError`     | Указать хотя бы один статус успеха                    |
| HealthSpec alias не пустая строка            | `HealthSpec._validate_alias`      | `ValueError`       | Указать непустой operation_alias                      |
| TargetSpec требует capability "check"        | `TargetSpec._validate_spec_integrity` | `ValueError`   | Добавить `check` в секцию `capabilities:`             |
| TargetSpec health alias есть в operations   | `TargetSpec._validate_spec_integrity` | `ValueError`   | Добавить операцию в каталог или исправить alias       |
| TargetSpec ключ operations == alias         | `TargetSpec._validate_spec_integrity` | `ValueError`   | Не писать alias вручную в YAML (он инжектируется)     |
| Неизвестное поле в YAML                      | Pydantic extra="forbid"           | `ValidationError`  | Убрать неизвестный ключ или исправить опечатку        |

### Диагностика через DslLoadError

Все ошибки валидации при загрузке через `load_target_spec()` оборачиваются в
`DslLoadError` с детализированным `details` словарём:

```python
# Пример: target_type не найден в registry
DslLoadError(
    code="TARGET_DSL_REGISTRY_MISSING",
    message="Target provider 'myidm' not found in registry.yml under 'targets:'",
    details={
        "target_type": "myidm",
        "available": ["ankey"],
    },
)

# Пример: невалидная спецификация
DslLoadError(
    code="TARGET_DSL_SPEC_INVALID",
    message="Invalid target spec for 'ankey': ...",
    details={
        "target_type": "ankey",
        "path": "/path/to/datasets/targets/ankey.target.yaml",
    },
)
```

Сообщение в `DslLoadError.message` содержит текст оригинального исключения Pydantic,
что позволяет быстро найти проблемное поле.

---

## 16. FAQ

**Q: Нужно ли писать `alias` в YAML?**

A: Нет. Поле `alias` в `OperationSpec` инжектируется автоматически из ключа словаря
в секции `operations`. Если написать `alias` вручную — он будет перезаписан значением
ключа на шаге `_inject_aliases`. Если написать расходящиеся alias и ключ — валидация
`TargetSpec` выбросит ошибку:

```
ValueError: operation alias key mismatch: key='users.upsert', alias='users.create'
```

---

**Q: Что значит «opaque data» в OperationSpec?**

A: Словарь `data` в `OperationSpec` непрозрачен для TargetKernel и domain-слоя.
Ядро не знает о `method`, `path_template`, `query_defaults` — это внутренние поля
транспортного слоя. `data` передаётся в `TransportCompilerRegistry.compile()` при
инициализации TargetKernel, и скомпилированный `CompiledOperation` хранится
отдельно от `OperationSpec`. Это позволяет добавлять новые транспортные протоколы
(gRPC, database) без изменения ядра.

---

**Q: Можно ли иметь несколько операций с `kind="grpc"`?**

A: Технически — да, если зарегистрировать компилятор для `"grpc"` в
`TransportCompilerRegistry`:

```python
registry.register("grpc", compile_grpc_operation)
```

Текущая реализация `AnkeyTargetProvider` регистрирует только `"http"`. При попытке
скомпилировать операцию с незарегистрированным `kind` — ошибка при инициализации
`TargetKernel`. Смешивать `kind="http"` и `kind="grpc"` в одном YAML-файле возможно,
если оба компилятора зарегистрированы.

---

**Q: Как переопределить redaction для одной операции?**

A: Используйте поле `redaction_override` в `OperationSpec`. Это словарь, структура
которого соответствует полям `RedactionSpec`. TargetKernel передаёт его в `safe_body()`
как аргумент `redaction`:

```yaml
operations:
  users.upsert:
    expected_statuses: [200, 201]
    redaction_override:
      body_mode: none        # не логировать тело для этой операции
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
```

```python
# В TargetKernel:
def safe_body(self, body: Any, redaction: RedactionSpec | None = None) -> Any:
    mode = (redaction or self._spec.redaction).body_mode
    ...
```

`redaction_override` обрабатывается вызывающим кодом (gateway/driver), а не
ядром напрямую. TargetKernel предоставляет `safe_body()` с опциональным параметром
`redaction` для этой цели.

---

**Q: Что если `match_reason` содержит заглавные буквы в YAML?**

A: Загрузчик Pydantic автоматически нормализует `match_reason` к нижнему регистру
в `RetryRule._validate_matcher()`. Таким образом, `match_reason: ResourceExists`
в YAML и `match_reason: resourceexists` — одно и то же правило:

```python
rule = RetryRule(directive="RETRY_BACKOFF", match_reason="ResourceExists")
assert rule.match_reason == "resourceexists"  # нормализовано
```

Аналогично, при сравнении в `resolve_retry_action()` `error_reason` от сервера
тоже нормализуется: `"resourceexists"` совпадёт с `"ResourceExists"` от Ankey API.

---

**Q: Можно ли не указывать `retry_config`?**

A: Нет. `retry_config: RetryConfig` в `TargetSpec` объявлено как обязательное поле
без дефолтного значения. Секция `retry_config:` обязана присутствовать в YAML. Если
устраивают дефолтные параметры, пишите явно:

```yaml
retry_config:
  max_attempts: 3
  backoff_base: 0.5
  backoff_max: 30.0
  jitter: true
```

Это сделано намеренно: явное объявление параметров повторов в YAML важно для
понимания поведения провайдера без чтения Python-кода.

---

**Q: Что происходит, если `fault_rules` пуст?**

A: Ядро создаётся без ошибок, но все ошибки будут классифицированы как `UNKNOWN`.
Retry-правила, основанные на `match_fault`, не смогут матчиться ни на какой
классифицированный fault, что эффективно означает NO_RETRY для всего. Это не
рекомендуется — список `fault_rules` должен покрывать типичные HTTP-ответы API.

---

**Q: Почему query_defaults значения должны быть строками?**

A: Параметры строки HTTP-запроса по протоколу передаются как строки. Транспортный
компилятор для HTTP обрабатывает `query_defaults` как `dict[str, str]`. YAML позволяет
писать числа (`page: 1`), но они будут интерпретированы как `int`, что может вызвать
ошибку типов в компиляторе. Безопаснее всегда оборачивать значения в кавычки:

```yaml
# ПРАВИЛЬНО
query_defaults:
  page: "1"
  rows: "10"

# ОПАСНО: YAML распознает как int, компилятор может отклонить
query_defaults:
  page: 1
  rows: 10
```

---

## 17. Тесты

Тест-файл: `tests/unit/infrastructure/test_target_spec.py`

### Покрытые сценарии

| Тест                                               | Что проверяет                                                           |
|----------------------------------------------------|-------------------------------------------------------------------------|
| `test_operation_alias_is_trimmed`                  | `OperationSpec.alias` обрезает пробелы при создании                     |
| `test_operation_alias_cannot_be_empty`             | Пустой/пробельный alias вызывает `ValueError`                           |
| `test_fault_rule_requires_matcher`                 | `FaultRule` без matcher вызывает `ValueError`                           |
| `test_retry_rule_requires_matcher`                 | `RetryRule` без matcher вызывает `ValueError`                           |
| `test_retry_rule_can_match_by_reason`              | `match_reason` и `mutation` корректно сохраняются                       |
| `test_retry_config_validates_backoff_bounds`       | `backoff_max < backoff_base` вызывает `ValueError`                      |
| `test_target_spec_rejects_operation_alias_key_mismatch` | Расхождение ключа и alias в operations вызывает `ValueError`       |
| `test_target_spec_rejects_missing_health_operation_alias` | Health alias, отсутствующий в operations, вызывает `ValueError` |

### Паттерн тестирования

Тесты разделены на два уровня:

1. **Юнит-тесты моделей** — создают модели напрямую с намеренно некорректными данными
   и проверяют, что `ValueError` поднимается с правильным сообщением.

2. **Интеграционные тесты через load_target_spec** — загружают реальный
   `ankey.target.yaml`, получают валидный `TargetSpec`, затем модифицируют
   его через `model_dump()` + `TargetSpec.model_validate()` для проверки
   инвариантов целостности.

```python
def test_target_spec_rejects_operation_alias_key_mismatch() -> None:
    # Шаг 1: загрузить реальную спецификацию
    spec = load_target_spec("ankey")
    payload = spec.model_dump()

    # Шаг 2: нарушить инвариант
    payload["operations"]["users.upsert"]["alias"] = "users.create"

    # Шаг 3: убедиться, что повторная валидация отклоняет
    with pytest.raises(ValueError, match="operation alias key mismatch"):
        TargetSpec.model_validate(payload)
```

Этот подход позволяет тестировать модель-валидаторы изолированно от файловой
системы и одновременно верифицировать, что реальный YAML корректно загружается.

### Запуск тестов

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_target_spec.py -v
```

---

## Связанные документы

- [DSL Engine](../dsl/dsl-engine.md) — общая DSL-инфраструктура (`DslLoadError`, `read_yaml`, `load_registry`)
- [Dictionary Layer](../dictionary/) — пример другого DSL-слоя в проекте
- [Vault Core](../vault/vault-core.md) — пример domain-слоя с портами и адаптерами
- `connector/domain/target_dsl/spec_models.py` — исходный код моделей
- `connector/domain/target_dsl/loader.py` — исходный код загрузчика
- `connector/infra/target/core/kernel.py` — TargetKernel: использование TargetSpec
- `connector/infra/target/providers/ankey_rest/provider.py` — AnkeyTargetProvider: wiring
- `datasets/targets/ankey.target.yaml` — реальная спецификация провайдера
- `datasets/registry.yml` — центральный реестр dataset'ов и targets
