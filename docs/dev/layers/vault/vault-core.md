# Vault Core

> **Бизнес-логика секретов в ETL-конвейере**: как секретные поля проходят путь `enrich -> plan -> apply` через порты, без привязки домена к конкретному хранилищу.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🎯 DSL (если применимо)](#-dsl-если-применимо)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
  - [🧾 Шаблон report для Vault](#-шаблон-report-для-vault)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [🗃️ SQLite профиль хранения (принято)](#️-sqlite-профиль-хранения-принято)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Управлять жизненным циклом секретных значений в transform/apply, чтобы секреты не оставались в обычном payload-потоке и подгружались только там, где действительно нужны.

**Ключевая ответственность**:
- На этапе enrich собрать секреты в `secret_candidates`, при наличии store-порта сохранить их и очистить рабочую строку.
- На этапе resolve/plan определить, какие секретные поля нужны для конкретной операции (`create`/`update`) и зафиксировать их в `secret_fields`.
- На этапе apply догидрировать обязательные секреты через read-порт и собрать финальный payload.

**Расположение в кодовой базе**:
- `connector/domain/ports/secrets/provider.py`
- `connector/domain/ports/secrets/` (target: `cipher.py`, `repository.py`, `key_provider.py`, `locator.py`)
- `connector/domain/secrets/` (target: `secret_vault_write_service.py`, `secret_vault_read_service.py`, `vault_startup_guard.py`, `secret_locator_service.py`)
- `connector/domain/transform/enrich/enricher_dsl.py`
- `connector/domain/transform/enrich/enricher_core.py`
- `connector/domain/transform_dsl/compilers/resolve.py`
- `connector/domain/transform/resolver/resolve_core.py`
- `connector/domain/planning/plan_builder.py`
- `connector/datasets/apply_adapter.py`
- `connector/infra/secrets/` (target: `fernet_envelope_cipher.py`, `sqlite/db.py`, `sqlite/repository.py`, `sqlite/schema.py`, `env_key_provider.py`)
- `connector/delivery/cli/bootstrap.py` (startup wiring + vault readiness guard)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/
├── domain/
│   ├── ports/secrets/provider.py                 # внешний контракт pipeline/apply
│   ├── ports/secrets/cipher.py                   # target: SecretCipherPort
│   ├── ports/secrets/repository.py               # target: SecretVaultRepositoryPort
│   ├── ports/secrets/key_provider.py             # target: VaultKeyProviderPort
│   ├── ports/secrets/locator.py                  # target: SecretLocatorPort
│   ├── secrets/secret_vault_write_service.py     # target: write business logic
│   ├── secrets/secret_vault_read_service.py      # target: read business logic
│   ├── secrets/secret_locator_service.py         # target: canonical locator/hash
│   ├── secrets/vault_startup_guard.py            # target: fail-fast startup key check
│   ├── transform/enrich/enricher_dsl.py          # DSL: перевод target -> secret:<field>
│   ├── transform/enrich/enricher_core.py         # _store_secrets + очистка row
│   ├── transform_dsl/compilers/resolve.py        # compile secrets.by_op policy
│   ├── transform/resolver/resolve_core.py        # перенос secret_fields в ResolvedRow
│   └── planning/plan_builder.py                  # перенос secret_fields в PlanItem
├── datasets/
│   └── apply_adapter.py                          # hydration секретов перед payload_builder
└── infra/
    ├── secrets/fernet_envelope_cipher.py         # crypto adapter
    ├── secrets/sqlite/db.py                      # target: vault sqlite connection/path policy
    ├── secrets/sqlite/repository.py              # target: sqlite vault repository adapter
    ├── secrets/sqlite/schema.py                  # target: vault-only migrations/schema lifecycle
    └── secrets/env_key_provider.py               # target: ENV key provider
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Enricher Class](../../../uml/transform/enricher/enricher_class.png) | Структура enrich-слоя, где формируются secret candidates |
| Sequence | [Enricher Sequence](../../../uml/transform/enricher/enricher_sequence.png) | Последовательность enrich-операций |
| Sequence | [Resolver Sequence](../../../uml/transform/resolver/resolver_sequence.png) | Последовательность match/resolve до plan |
| Activity | [Resolver Activity](../../../uml/transform/resolver/resolver_activity.png) | Поток resolve и принятия решения по op |

**PlantUML исходники**:
- `docs/uml/transform/enricher/*.puml`
- `docs/uml/transform/resolver/*.puml`

> Примечание: отдельные UML для vault-storage/crypto ещё не заведены; текущий документ описывает фактический runtime-контур.

### 🎭 Применённые паттерны

#### Паттерн 1: Hexagonal Ports (Read/Write Secrets)

**Где применяется**: Изоляция доменного кода от источника/хранилища секретов.

**Реализация в коде**:
- **Read port**: `SecretProviderProtocol` в `connector/domain/ports/secrets/provider.py`
- **Write port**: `SecretStoreProtocol` в `connector/domain/ports/secrets/provider.py`
- **Current adapters**: `SecretVaultReadService`/`SecretVaultWriteService` (domain orchestration) + `SqliteVaultRepository` (infra storage)

**Пример использования**:
```python
class SecretStoreProtocol(Protocol):
    def put_many(
        self,
        *,
        dataset: str,
        match_key: str,
        secrets: dict[str, str],
        run_id: str | None = None,
    ) -> None: ...
```

**Зачем**: Enricher/Apply работают только по контракту и не зависят от конкретного backend хранения/чтения секретов.

#### Паттерн 1.1: Separate bounded context for Vault storage

**Где применяется**: Разделение Vault и Cache на уровне портов.

**Реализация в коде**:
- Vault read/write идут через `SecretVaultRepositoryPort` (target).
- Cache read/write идут через `EnrichLookupPort`/`PlanningRuntimePort` и другие cache role-порты.

**Зачем**: Даже при общем физическом SQLite не возникает доменной связности между cache и vault.

#### Паттерн 2: Two-phase secret lifecycle

**Где применяется**:
- Фаза 1 (plan-time): собрать и сохранить секреты в enrich.
- Фаза 2 (apply-time): восстановить секреты в payload только для нужных операций.

**Реализация в коде**:
- **Capture/Store**: `EnricherCore._store_secrets()` в `connector/domain/transform/enrich/enricher_core.py`
- **Policy**: `ResolveDsl._compile_secrets()` в `connector/domain/transform/resolver/resolve_dsl.py`
- **Hydration**: `OperationApplyAdapter._hydrate_payload_source()` в `connector/datasets/apply_adapter.py`
- **Target write/read services**: `SecretVaultWriteService`, `SecretVaultReadService` в `connector/domain/secrets/`

**Зачем**: Секреты не проходят весь ETL как обычные поля и извлекаются только в последней точке.

#### Паттерн 3: Policy-driven secret exposure

**Где применяется**: DSL определяет `secret_fields` отдельно для `create` и `update`.

**Реализация в коде**:
- DSL: `datasets/employees.resolve.yaml`
- Компиляция policy: `ResolveDsl._compile_secrets()`
- Применение policy: `ResolveCore.resolve()`

**Зачем**: Бизнес может менять правила “когда нужен секрет” без изменения apply-кода.

### Диаграмма зависимостей

```
[Enrich DSL] -> [EnricherDsl] -> [EnricherCore] -> SecretStoreProtocol
                                         |
                                         v
                                meta.secret_fields + row cleanup
                                         |
[Resolve DSL secrets.by_op] -> [ResolveDsl] -> [ResolveCore] -> ResolvedRow.secret_fields
                                                              |
                                                              v
                                                        [PlanBuilder]
                                                              |
                                                              v
                                                       PlanItem.secret_fields
                                                              |
                                                              v
                                                  [OperationApplyAdapter]
                                                              |
                                                              v
                                                     SecretProviderProtocol
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Где используется |
|-----------|-----------|------------------|
| `SecretStoreProtocol` | Запись набора секретов на plan-time | `EnricherCore._store_secrets()` |
| `SecretProviderProtocol` | Получение секрета по контексту plan-item | `OperationApplyAdapter._hydrate_payload_source()` |
| `SecretCipherPort` (target) | Шифрование/дешифрование payload секрета | `SecretVaultWriteService`, `SecretVaultReadService` |
| `SecretVaultRepositoryPort` (target) | Хранение ciphertext/metadata/probe | `SecretVaultWriteService`, `SecretVaultReadService`, `VaultStartupGuard` |
| `VaultKeyProviderPort` (target) | Источник и версия master keys из ENV | cipher lifecycle + startup guard |
| `SecretLocatorPort` (target) | Детерминированный `locator_hash` из `dataset+field+source_ref` | write/read services |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `EnricherDsl` | DSL->runtime трансляция секретных targets в `secret:<field>` | `_build_generate_operation()` |
| `EnricherCore` | Сохранение секретов, очистка row, запись `meta.secret_fields` | `_store_secrets()`, `_clear_secret_fields()` |
| `ResolveDsl` | Политика `secret_fields` по операции (`create`/`update`) | `_compile_secrets()` |
| `ResolveCore` | Подстановка `secret_fields` в `ResolvedRow` | `resolve()` |
| `PlanBuilder` | Перенос `secret_fields` в `PlanItem` артефакт | `add_resolved()` |
| `OperationApplyAdapter` | Догидрация секретов перед построением payload | `_hydrate_payload_source()` |
| `SecretVaultWriteService` (target) | Принять plaintext secret, построить locator, зашифровать, сохранить | `put_many()` |
| `SecretVaultReadService` (target) | Найти запись по locator, проверить metadata, расшифровать | `get_secret()` |
| `SecretLocatorService` (target) | Канонизировать `source_ref` и вычислить hash | `build_locator_hash()` |
| `VaultStartupGuard` (target) | Fail-fast startup readiness check по ключам/probe | `ensure_ready()` |
| `SqliteVaultRepository` | Хранение ciphertext/DEK/probe в отдельном vault SQLite | `upsert_secret()`, `get_secret()`, `upsert_dek()`, `get_probe()` |

---

## 🗂️ Модели данных

### Dataclass: `TransformResult`

**Назначение**: Унифицированный контейнер transform-стадий, в котором секреты временно живут как `secret_candidates`.

**Структура**:
```python
@dataclass(frozen=True, slots=True)
class TransformResult(Generic[T]):
    record: SourceRecord
    row: T | None
    row_ref: RowRef | None
    match_key: MatchKey | None
    meta: Mapping[str, Any] = field(default_factory=dict)
    secret_candidates: Mapping[str, str] = field(default_factory=dict)
    errors: tuple[DiagnosticItem, ...] = field(default_factory=tuple)
    warnings: tuple[DiagnosticItem, ...] = field(default_factory=tuple)
```

**Lifecycle**:
1. Создаётся после map/normalize как часть потока.
2. В enrich `secret_candidates` пополняются через target `secret:<field>`.
3. После `_store_secrets()` поля очищаются из row, а `meta["secret_fields"]` фиксируется.

**Инварианты**:
- `meta` и `secret_candidates` freeze-ятся в immutable mapping при build.
- Если секреты сохранены/обработаны в enrich, `secret_candidates` очищается до конца стадии.

### Dataclass: `PlanItem`

**Назначение**: Единица apply-плана с меткой, какие секретные поля нужно догидрировать.

**Структура**:
```python
@dataclass
class PlanItem:
    row_id: str
    line_no: int | None
    op: str
    target_id: str
    desired_state: dict[str, Any]
    changes: dict[str, Any]
    source_ref: dict[str, Any] | None = None
    secret_fields: list[str] = field(default_factory=list)
```

**Lifecycle**:
1. Формируется из `ResolvedRow` в `PlanBuilder.add_resolved()`.
2. Сериализуется в plan-артефакт с `secret_fields`.
3. Используется `OperationApplyAdapter` в apply.

**Инварианты**:
- `secret_fields` содержит только названия полей (без значений).
- Если список пуст, apply не делает обращений к `SecretProviderProtocol`.

### Target model: `VaultSecretRecord` (production vault)

**Назначение**: Хранимая запись секрета в repository-слое (opaque ciphertext + operational metadata).

**Структура (целевой контракт)**:
```python
@dataclass(frozen=True)
class VaultSecretRecord:
    dataset: str
    field: str
    locator_hash: str
    locator_version: str
    ciphertext: bytes | str
    cipher_algo: str
    key_version: str
    dek_version: str
    run_id: str | None
    created_at: str
    updated_at: str
```

**Инварианты**:
- `ciphertext` непрозрачен для бизнес-логики (не парсится вне `SecretCipherPort`).
- `locator_hash` детерминирован для одного и того же `(dataset, field, canonical source_ref)`.
- `locator_version` хранится в каждой записи и участвует в read/write контрактах.
- `cipher_algo` определяет crypto-engine для конкретной записи (crypto-agility).
- В metadata нет plaintext секрета и его реконструируемых частей.

### Target model: `VaultDekRecord`

**Назначение**: Хранение DEK в wrapped-виде с версией/алгоритмом обёртки.

**Структура (целевой контракт)**:
```python
@dataclass(frozen=True)
class VaultDekRecord:
    dek_version: str
    wrapped_dek: bytes | str
    wrap_algo: str
    wrap_key_version: str
    is_active: bool
    created_at: str
    updated_at: str
```

**Инварианты**:
- `wrapped_dek` не содержит plaintext DEK.
- `wrap_algo` хранится в записи и используется для выбора unwrap-движка.
- Активный DEK ровно один для write-path.

### Target model: `VaultProbeRecord`

**Назначение**: Служебная startup-запись для проверки совместимости ключей.

**Инварианты**:
- читается и дешифруется при запуске через `VaultStartupGuard`;
- не содержит пользовательских секретов;
- используется только для readiness/fail-fast.

### Профиль хранения в Vault SQLite

**Назначение**: production-ready хранение ciphertext/метаданных в отдельной SQLite БД.

**Ключевые таблицы**:
```text
vault_secrets, vault_dek, vault_probe, vault_meta
```

**Инварианты**:
- lookup выполняется по `dataset + field + locator_version + locator_hash (+/- run_id)`;
- plaintext секретов не хранится в storage;
- read-path соблюдает run precedence `exact run_id -> global (NULL)`.

---

## 🎯 DSL (если применимо)

Секретная бизнес-логика определяется в двух DSL-блоках:

1. `enrich.secrets.fields`:
   - в `datasets/employees.enrich.yaml` поле `password` объявлено как секрет;
   - при компиляции `EnricherDsl` преобразует target `password` в `secret:password`.
2. `resolve.secrets.mode=by_op`:
   - в `datasets/employees.resolve.yaml` задано: `create: [password]`, `update: []`;
   - `ResolveDsl._compile_secrets()` превращает это в runtime-policy для `ResolveCore`.

Ключевой эффект:
- enrich отвечает за сбор и запись значения секрета;
- resolve отвечает за то, попадёт ли имя этого поля в `PlanItem.secret_fields` для конкретной операции.

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `EnricherCore._store_secrets()` | ~37 | O(s) | Запись секретов, фиксация `secret_fields`, очистка row |
| `OperationApplyAdapter._hydrate_payload_source()` | ~27 + I/O | O(s + lookup) | Догидрация секретов перед payload builder |
| `ResolveDsl._compile_secrets()` | ~15 | O(1) | Компиляция policy `create/update -> secret_fields` |
| `ResolveCore.resolve()` (блок secrets) | ~20 | O(1) | Вычисление `secret_fields` и перенос в `ResolvedRow` |
| `SecretLocatorService.build_locator_hash()` (target) | ~20 | O(k log k) | Канонизация `source_ref` и расчёт стабильного locator hash |
| `VaultStartupGuard.ensure_ready()` (target) | ~40 + I/O | O(1) | Fail-fast проверка ключей и decrypt служебной probe |

где:
- `s` — количество полей в `secret_fields`;
- `lookup` — стоимость получения секрета в конкретной adapter-реализации.
- `k` — количество ключей в `source_ref`.

### Метод: `EnricherCore._store_secrets()`

**Расположение**: `connector/domain/transform/enrich/enricher_core.py:532`

**Сигнатура**:
```python
def _store_secrets(
    self,
    builder: TransformResultBuilder[T],
) -> None:
```

**Назначение**:
Сохранить секретные значения через `SecretStoreProtocol`, затем удалить их из runtime-row и оставить только имена полей в `meta.secret_fields`.

---

**Алгоритм**:
```
1. Exit early, если secret_candidates пуст
2. Проверить, что есть match_key
   - если нет -> MATCH_KEY_MISSING + return
3. Если secret_store подключён:
   - вызвать put_many(dataset, match_key, secrets, run_id)
   - при исключении -> SECRET_STORE_ERROR
4. Сформировать secret_fields = keys(secret_candidates)
5. Записать builder.meta["secret_fields"] = secret_fields
6. Очистить секретные поля в row (set None)
7. Очистить builder.secret_candidates = {}
```

**Временная сложность**:
- **Best case**: O(1), когда `secret_candidates` пуст.
- **Average/Worst**: O(s) + стоимость `secret_store.put_many(...)`.

**Инварианты**:
1. После выполнения `secret_candidates` очищается.
2. В `meta.secret_fields` остаются только названия полей.
3. При отсутствии `match_key` запись в store не выполняется.

**Edge cases**:
1. Нет `match_key`: добавляется ошибка `MATCH_KEY_MISSING`.
2. Ошибка storage adapter: добавляется `SECRET_STORE_ERROR`, но стадия не падает исключением.
3. `row` может быть `dict` или объектом; очистка работает для обоих случаев.

---

### Метод: `OperationApplyAdapter._hydrate_payload_source()`

**Расположение**: `connector/datasets/apply_adapter.py:49`

**Сигнатура**:
```python
def _hydrate_payload_source(self, item: PlanItem) -> dict[str, Any]:
```

**Назначение**:
Для каждого поля из `item.secret_fields` обеспечить значение в `payload_source` через `SecretProviderProtocol`.

---

**Алгоритм**:
```
1. payload_source = copy(item.desired_state)
2. FOR EACH secret_field IN item.secret_fields:
   - если значение уже есть в payload_source -> skip
   - иначе вызвать secrets.get_secret(...) с контекстом plan-item
   - если секрет отсутствует -> raise MissingRequiredSecretError
   - иначе положить секрет в payload_source
3. return payload_source
```

**Временная сложность**:
- **Best case**: O(s), если все секреты уже в `desired_state`.
- **Worst case**: O(s + s*lookup), если каждый секрет читается из внешнего хранилища.

**Инварианты**:
1. Поля вне `item.secret_fields` не догидрируются.
2. Отсутствующий обязательный секрет переводится в контролируемое исключение `SECRET_REQUIRED`.
3. apply-слой не знает, где физически лежит секрет.

**Edge cases**:
1. `secrets` provider не задан: любой требуемый secret приводит к `MissingRequiredSecretError`.
2. `source_ref` без match-идентификатора: многие реализации provider вернут `None`.
3. Если `payload_builder` требует поле, которое не в `secret_fields`, ошибка возникнет уже на этапе построения payload.

---

### Метод: `ResolveDsl._compile_secrets()`

**Расположение**: `connector/domain/transform/resolver/resolve_dsl.py:210`

**Сигнатура**:
```python
def _compile_secrets(spec: ResolveSecretsSpec | None) -> SecretFieldsPolicy | None:
```

**Назначение**:
Собрать функцию-политику, которая по операции resolve (`create`/`update`) возвращает список `secret_fields`.

---

**Алгоритм**:
```
1. Если spec отсутствует или mode == "none" -> None
2. Зафиксировать create_fields и update_fields из DSL
3. Вернуть функцию policy(op, desired_state, existing):
   - op == "create" -> create_fields
   - op == "update" -> update_fields
   - иначе []
```

**Инварианты**:
1. Политика детерминирована и не зависит от adapter-инфраструктуры.
2. По умолчанию для неизвестной операции возвращается пустой список.
3. `desired_state`/`existing` сейчас не участвуют в вычислении (чисто op-based policy).

---

### Метод (target): `SecretLocatorService.build_locator_hash()`

**Расположение**: `connector/domain/secrets/secret_locator_service.py`

**Назначение**:
Сформировать единый ключ адресации секрета, одинаковый для write-path (enrich) и read-path (apply).

**Алгоритм**:
```
1. Взять dataset, field, source_ref
2. Канонизировать source_ref:
   - удалить пустые/None значения
   - отсортировать ключи
   - стабильно сериализовать в JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`)
3. Собрать locator string: `v1|<dataset>|<field>|<canonical_json>`
4. Посчитать `sha256(locator_string)`
5. Вернуть hex digest как `locator_hash`
```

**Инварианты**:
1. Эквивалентные `source_ref` всегда дают один hash.
2. Канонизация строго структурная (без `trim/lower/semantic normalize` значений).
3. Изменение алгоритма канонизации считается breaking-change и требует миграции.
4. Raw `source_ref` не сохраняется в vault storage.

---

### Метод (target): `VaultStartupGuard.ensure_ready()`

**Расположение**: `connector/domain/secrets/vault_startup_guard.py`

**Назначение**:
Остановить приложение до запуска pipeline, если vault-ключи некорректны или запись в vault нельзя расшифровать.

**Алгоритм**:
```
1. Проверить, что key-provider вернул валидный активный ключ и набор fallback ключей
2. Проверить доступность vault repository
3. Прочитать служебную probe-запись
   - если нет -> создать (encrypt + persist)
4. Дешифровать probe
   - при ошибке -> VaultStartupKeyValidationError
5. Вернуть success и залогировать только служебный статус
```

**Инварианты**:
1. В `vault`-режиме startup без успешного `ensure_ready()` запрещён.
2. Ключи и plaintext probe не попадают в логи.
3. Проверка выполняется один раз на bootstrap, до пользовательских операций.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Что передаёт в Vault Core | Что получает обратно |
|------|---------------------------|----------------------|
| Transform Enrich | `secret_candidates`, `match_key`, `run_id` | запись в store (или ошибки) + очищенный row |
| Resolve/Planning | `op`, `desired_state`, `existing` | `ResolvedRow.secret_fields`, затем `PlanItem.secret_fields` |
| Apply/Target | `PlanItem.secret_fields` + контекст записи | догидрированный payload-source |
| Diagnostics/Reporting | `meta.secret_fields` и `secret_candidates` | masked payload (`***`) и counters по secret-candidates |
| Reporting Collector/Presenter | diagnostics/errors на boundary | `ReportEnvelope` (`meta/summary/items/context`) без plaintext/key leakage |

Поток данных:

```
source row
  -> map/normalize
  -> enrich(secret capture/store + row cleanup)
  -> match/resolve(secret_fields policy)
  -> plan artifact(secret_fields only)
  -> apply(secret hydration)
  -> target request payload
```

Инкапсуляция reporting-инструментов:
- Vault domain services не зависят от `ReportCollector` и report-моделей напрямую.
- Преобразование событий в report происходит на boundary-слое:
  - `connector/domain/transform/core/result_processor.py` — row-level отчёты для transform/enrich/planning.
  - `connector/delivery/presenters/apply_report_presenter.py` — apply-result -> report items/summary.
  - `connector/domain/reporting/diagnostics.py` — `DiagnosticItem -> ReportDiagnostic`.
  - `connector/common/sanitize.py` — маскирование payload (`maskSecretsInObject`) перед записью в отчёт.

---

## 🔌 Контракты и границы

1. **Domain-контракт хранения**:
   - `SecretStoreProtocol.put_many(dataset, match_key, secrets, run_id)`.
   - Domain не знает формат записи в backend.

2. **Domain-контракт чтения**:
   - `SecretProviderProtocol.get_secret(dataset, field, row_id, line_no, source_ref, target_id, run_id)`.
   - Apply adapter не знает, откуда пришёл секрет (vault/prompt/другое).

3. **Бизнес-граница секретов**:
   - Значения секретов живут в `secret_candidates` только до конца enrich.
   - Дальше по pipeline идут только названия в `secret_fields`.

4. **Граница Vault vs Cache**:
   - Vault не использует cache role-порты для CRUD секретов.
   - Vault хранится в отдельном SQLite-файле (по умолчанию рядом с cache DB).
   - Доступ к vault идёт через отдельный `SecretVaultRepositoryPort`.

5. **Startup readiness boundary (target)**:
   - В `vault`-режиме bootstrap обязан вызвать `VaultStartupGuard.ensure_ready()` до старта use-case.
   - При ошибке key/decrypt приложение завершается fail-fast, а не продолжает работу до первого apply/read запроса.

6. **Runtime mode policy (target)**:
   - `source="vault"` означает vault-only без prompt fallback.
   - Интерактивный prompt допускается только в явном `source="prompt"` режиме.

7. **Reporting encapsulation boundary**:
   - Vault-сервисы возвращают доменные результаты/исключения и не формируют report-структуры.
   - В diagnostics/reporting слой попадает только нормализованный сигнал:
     - row-level через `DiagnosticItem` (enrich/apply);
     - system-level через command/boundary ошибки (startup guard, key config).
   - Маскирование секретов выполняется до попадания payload в `ReportItem`.

8. **Locator v1 contract (принято)**:
   - hash-формула: `sha256("v1|<dataset>|<field>|<canonical_source_ref_json>")`;
   - canonical JSON: только сортировка ключей + удаление пустых значений, без модификации самих значений;
   - в storage хранится `locator_hash` + `locator_version` (raw `source_ref` не хранится);
   - read-path сначала использует `run_id` exact match, затем fallback на global запись (`run_id IS NULL`);
   - read-path строится как совместимый по версиям locator (сейчас список `["v1"]`).

9. **Locator evolution policy (v1 -> v2)**:
   - текущий production baseline — `v1`;
   - `v2` вводится только при реальном breaking-case, не проактивно;
   - при появлении `v2` применяется dual-read (`v2`, затем `v1`) и фоновый rewrite/migration.

10. **SQLite topology policy (принято)**:
   - vault использует отдельный SQLite-файл (по умолчанию `cache/ankey_vault.sqlite3`);
   - путь может быть переопределён через `ANKEY_VAULT_DB_PATH`;
   - внутри vault DB используется отдельный schema-модуль (`connector/infra/secrets/sqlite/schema.py`) и `vault_*` таблицы;
   - доменный доступ к этим таблицам идёт только через `SecretVaultRepositoryPort`.

11. **SQLite module placement (принято)**:
   - vault repository не размещается в `connector/infra/cache/repository/`;
   - целевая структура: `connector/infra/secrets/sqlite/db.py` + `connector/infra/secrets/sqlite/schema.py` + `connector/infra/secrets/sqlite/repository.py`;
   - переиспользуются только низкоуровневые SQLite-инструменты (`db.py`/`engine.py`) без reuse cache role-портов.

12. **Index policy (принято)**:
   - отдельный индекс на surrogate `id` не добавляется, если поле объявлено `PRIMARY KEY`;
   - рабочие индексы строятся по lookup-контракту (`dataset`, `field`, `locator_version`, `locator_hash`, `run_id`).

13. **Timestamp policy (принято)**:
   - `created_at/updated_at` хранятся в UTC ISO-8601 (`TEXT`);
   - `updated_at` задаётся приложением на каждом upsert/update;
   - DB `DEFAULT CURRENT_TIMESTAMP` допускается как fallback для `created_at`, но не как единственный источник `updated_at`.

14. **Crypto-agility metadata policy (принято)**:
   - в `vault_secrets` хранится `cipher_algo` (например, `FERNET_V1`);
   - в `vault_dek` хранится `wrap_algo` (например, `FERNET_V1`);
   - выбор crypto-движка выполняется по полю `algo` конкретной записи.

15. **Delivery strategy (принято)**:
   - этап 1 (MVP): минимальный отдельный vault backend в `cache/ankey_vault.sqlite3` без платформенного refactor общей multi-DB модели;
   - этап 2 (архитектурный трек): унификация подключения/регистрации нескольких DB-файлов в единой модели инфраструктуры;
   - этап 1 не блокируется ожиданием этапа 2.

---

## 💡 Типичные сценарии

### Сценарий 1: Create с генерацией пароля

1. `datasets/employees.enrich.yaml` генерирует `password`, а `enrich.secrets.fields` помечает его секретом.
2. `EnricherCore` записывает секрет через `SecretStoreProtocol`, очищает `row.password`, фиксирует `meta.secret_fields=["password"]`.
3. `ResolveDsl` для `create` возвращает `["password"]`, `PlanBuilder` переносит это в `PlanItem.secret_fields`.
4. `OperationApplyAdapter` читает пароль через `SecretProviderProtocol` и формирует payload.

### Сценарий 2: Update без секрета в policy

1. В `datasets/employees.resolve.yaml` `update: []`.
2. `PlanItem.secret_fields` пустой, apply не делает secret lookup.
3. Если payload-builder требует `password` как обязательное поле, он выбросит ошибку missing fields.

### Сценарий 3: План построен при отключённом vault-mode

1. Enrich может собрать `secret_candidates`.
2. Если запуск выполнен с `--vault-mode off`, запись в vault запрещена и команда должна завершиться fail-fast при наличии секретных полей.
3. `import apply` при `--vault-mode off` и `secret_fields` в плане также завершается fail-fast до чтения секрета.

### Сценарий 4 (target): Startup с неверным ключом

1. Bootstrap запускает `VaultStartupGuard.ensure_ready()`.
2. Guard читает probe-запись и пытается decrypt текущим набором ключей.
3. При несовместимости ключа бросается `VaultStartupKeyValidationError`.
4. Приложение завершает запуск до выполнения `import plan/apply`.

### 🧾 Шаблон report для Vault

Ниже шаблон для row-level vault ошибки (например, `SECRET_REQUIRED` на apply/enrich boundary):

```json
{
  "status": "PARTIAL",
  "meta": {
    "run_id": "<run_id>",
    "dataset": "employees",
    "command": "import-apply",
    "started_at": "<ISO-8601>",
    "finished_at": "<ISO-8601>",
    "duration_ms": 1234,
    "items_limit": 200,
    "items_truncated": false
  },
  "summary": {
    "rows_total": 100,
    "rows_passed": 99,
    "rows_blocked": 1,
    "rows_with_warnings": 0,
    "errors_total": 1,
    "warnings_total": 0,
    "by_stage": {
      "APPLY": {
        "errors_total": 1,
        "warnings_total": 0
      }
    },
    "ops": {
      "create": {"ok": 50, "failed": 0, "count": 0},
      "update": {"ok": 49, "failed": 1, "count": 0},
      "apply_failed": {"ok": 0, "failed": 1, "count": 0}
    }
  },
  "items": [
    {
      "status": "FAILED",
      "row_ref": {
        "line_no": 42,
        "row_id": "src-42",
        "identity_primary": null,
        "identity_value": null
      },
      "payload": {
        "password": "***"
      },
      "diagnostics": [
        {
          "severity": "error",
          "stage": "APPLY",
          "code": "SECRET_REQUIRED",
          "field": "password",
          "message": "Missing required secret 'password' (...)",
          "rule": null
        }
      ],
      "meta": {
        "op": "update",
        "target_id": "100500"
      }
    }
  ],
  "context": {
    "apply": {
      "error_stats": {"SECRET_REQUIRED": 1},
      "target_runtime_mode": "rest"
    }
  }
}
```

Шаблон для system-level startup ошибки (`VaultStartupKeyValidationError`, без row items):

```json
{
  "status": "FAILED",
  "meta": {
    "run_id": "<run_id>",
    "dataset": "employees",
    "command": "import-apply"
  },
  "summary": {
    "rows_total": 0,
    "rows_passed": 0,
    "rows_blocked": 0,
    "errors_total": 1
  },
  "items": [],
  "context": {
    "vault_startup": {
      "ready": false,
      "error_code": "VAULT_STARTUP_KEY_VALIDATION_ERROR"
    }
  }
}
```

Правила шаблона:
- `items[].payload` всегда маскируется (`***`) для секретных ключей.
- Для vault-диагностик использовать только служебные коды/контекст; ключи, ciphertext и plaintext в report не писать.
- Row-level и system-level кейсы разделяются: первая группа идёт через `items`, вторая — через `context` + status command-level.

---

## 📌 Важные детали

### 🚨 Failure Modes

1. `MATCH_KEY_MISSING` в enrich: есть секреты, но отсутствует `match_key` для адресации в store.
2. `SECRET_STORE_ERROR` в enrich: adapter записи бросил исключение.
3. `SECRET_REQUIRED` в apply: `secret_fields` требуют поле, но provider вернул `None`.
4. `UNEXPECTED_ERROR` в apply: payload builder упал из-за отсутствующих обязательных полей (например, `password`).
5. Пустой/некорректный `source_ref`: provider не находит секрет даже при наличии записи.
6. `VaultStartupKeyValidationError` (target): при старте probe-запись не decrypt-ится текущими ключами.
7. `SecretIntegrityError` (target): ciphertext/metadata повреждены или подменены.
8. Locator policy drift (target): write/read строят разный hash, что даёт массовые misses.
9. Run scope mismatch (target): запись есть только в другом `run_id`, а policy fallback не учтён.

### 🗃️ SQLite профиль хранения (принято)

Базовый storage-профиль для v1:

```sql
CREATE TABLE IF NOT EXISTS vault_dek (
    dek_version TEXT PRIMARY KEY,
    wrapped_dek BLOB NOT NULL,
    wrap_algo TEXT NOT NULL,
    wrap_key_version TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vault_secrets (
    secret_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset TEXT NOT NULL,
    field TEXT NOT NULL,
    locator_hash TEXT NOT NULL,
    locator_version TEXT NOT NULL,
    run_id TEXT,
    ciphertext BLOB NOT NULL,
    cipher_algo TEXT NOT NULL,
    key_version TEXT NOT NULL,
    dek_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_secret_unique_scope
ON vault_secrets(dataset, field, locator_version, locator_hash, COALESCE(run_id, ''));

CREATE INDEX IF NOT EXISTS idx_vault_secret_lookup
ON vault_secrets(dataset, field, locator_version, locator_hash, run_id);

CREATE TABLE IF NOT EXISTS vault_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

Правила профиля:
- vault хранится в отдельном SQLite-файле рядом с cache (`cache/ankey_vault.sqlite3` по умолчанию);
- отдельная БД-схема/namespace SQLite не вводится (в SQLite её нет); под «отдельной схемой» в этом контексте понимается отдельный файл схемы/миграций `connector/infra/secrets/sqlite/schema.py`;
- versioning vault хранится отдельно (`vault_meta.key='schema_version'`), чтобы миграции vault не зависели от cache schema version;
- отдельный индекс на `secret_id` не нужен, он уже покрыт `PRIMARY KEY`;
- `DEFAULT (STRFTIME(...))` не используется как базовая стратегия времени: `updated_at` выставляется приложением детерминированно.

### ⚠️ Инварианты системы

1. Секретное значение не должно оставаться в `row` после `_store_secrets()` для полей из `secret_fields`.
2. `PlanItem.secret_fields` содержит только имена полей, не значения.
3. Apply обращается к `SecretProviderProtocol` только для полей из `PlanItem.secret_fields`.
4. Report/diagnostics маскируют секретные поля (`***`) и не печатают raw secret.
5. Domain-слой не зависит от конкретной реализации vault/storage.
6. Vault в домене отделён от cache-портов и хранится в отдельном DB-файле.
7. В `vault`-режиме запуск без успешного startup guard запрещён.
8. Locator строится детерминированно из канонического `source_ref`.
9. Для locator всегда фиксируется `locator_version` и соблюдается `run_id` precedence (`exact -> global`).

### ⏱️ Performance заметки

1. `SqliteVaultRepository` использует lookup-индексы по locator/run scope; типичный read-path близок к O(log n).
2. `_hydrate_payload_source()` вызывает provider по каждому secret field; при удалённом backend важно batch/кеширование.
3. `_store_secrets()` записывает секреты по одному проходу `for field, value in secrets.items()`, что линейно по количеству secret fields.

---

## 🛠️ Как расширять

1. Сохраняй внешний контракт pipeline/apply:
   - не менять сигнатуры `SecretStoreProtocol`/`SecretProviderProtocol` без migration plan.

2. Новую бизнес-логику vault добавляй в `connector/domain/secrets/`:
   - write/read orchestration, locator policy, startup readiness, lifecycle ключей.
   - adapter-детали (SQLite/Fernet/ENV) сюда не переносить.

3. Новые микрофичи добавляй по назначению:
   - **Health/key readiness check**: `connector/domain/secrets/vault_startup_guard.py`, вызов из `connector/delivery/cli/bootstrap.py`;
   - **Крипто-правила и envelope flow**: `connector/domain/secrets/secret_vault_write_service.py` + `secret_vault_read_service.py`;
   - **Locator policy/версионирование**: `connector/domain/secrets/secret_locator_service.py`;
   - **Storage schema/query tuning**: `connector/infra/secrets/sqlite/schema.py` + `connector/infra/secrets/sqlite/repository.py`.

4. Минимальная модульность SQLite adapter:
   - одного файла недостаточно для поддерживаемого роста;
   - минимум 2 модуля: `schema.py` (DDL + migrations) и `repository.py` (CRUD/queries);
   - при расширении допускается `mapper.py`/`errors.py`, но порты домена не меняются.

5. Новые backend-реализации добавляй как infra adapters:
   - crypto adapter реализует `SecretCipherPort`;
   - repository adapter реализует `SecretVaultRepositoryPort`;
   - key-provider adapter реализует `VaultKeyProviderPort`;
   - wiring делается в bootstrap/composition root.

6. Перед включением backend в runtime:
   - покрыть unit-тестами `SECRET_REQUIRED`, run_id precedence, locator determinism, startup guard fail-fast;
   - проверить, что логи/репорты не содержат ключей и plaintext.

7. Если нужен op-aware payload-контракт:
   - синхронизировать `resolve.secrets.by_op` и требования `payload_builder`;
   - иначе update/create могут расходиться по обязательным полям.

8. Эволюция locator:
   - `v1` считать стабильным контрактом до появления доказанного breaking-case;
   - заранее поддерживать в read-path список совместимых версий (сейчас `["v1"]`);
   - при вводе `v2` не ломать старые записи: dual-read + controlled migration.

---

## 🔗 Связанные документы

- [VAULT-PROBLEM-001](../../../adr/vault/VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md)
- [VAULT-DEC-001](../../../adr/vault/VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)
- [Resolve Core](../resolver/resolve-core.md)
- [Resolve DSL](../resolver/resolve-dsl.md)
- [DSL Engine](../dsl/dsl-engine.md)
- [Dev INDEX](../../INDEX.md)

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Vault Core | xORex-LC |