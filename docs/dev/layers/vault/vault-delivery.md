# Vault Layer — Delivery

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Delivery-слой vault связывает CLI UX, DI composition root,
runtime startup guard и usecase-операции управления vault.

**Ключевая ответственность**: prompt/CLI orchestration, wiring зависимостей,
инициализация SQLite schema/startup guard и передача unseal passphrase в
`VaultContainer`.

**Расположение в кодовой базе**:
- `connector/delivery/commands/vault_management.py`
- `connector/delivery/commands/vault_unseal.py`
- `connector/delivery/cli/containers.py`
- `connector/usecases/management/vault`

Delivery не реализует KDF/HMAC, не хранит master key и не читает persisted
keyring. Его роль — получить runtime input от оператора и передать его в уже
собранный object graph.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```text
connector/delivery/
├── cli/
│   ├── app.py          # Typer command surface
│   └── containers.py   # AppContainer, SqliteContainer, VaultContainer
└── commands/
    ├── vault_management.py # init/status/rotate/rewrap UX
    ├── vault_unseal.py     # runtime unseal prompt helper
    ├── enrich.py           # runtime command using vault write path
    ├── import_plan.py      # runtime command using vault write path
    └── import_apply.py     # runtime command using vault read path

connector/usecases/management/vault/
├── usecase.py         # lifecycle orchestration
├── verify.py          # startup guard post-verify adapter
├── contracts.py       # usecase protocols
└── models.py          # status/result DTOs
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Overview | [Vault UML index](../../../uml/vault/README.md) | Индекс актуальных и исторических диаграмм vault |

### 🎭 Применённые паттерны

#### Composition Root

**Где применяется**: `AppContainer`, `SqliteContainer`, `VaultContainer`.

**Реализация в коде**:
- `AppContainer.vault_unseal_passphrase` — runtime object provider.
- `SqliteContainer.vault_ready` — schema + unseal startup resource.
- `VaultContainer.key_provider` — `UnsealedVaultKeyProvider` над vault repository.

**Зачем**: `VaultContainer` не спрашивает пользователя и не читает ENV; все
runtime inputs приходят извне от composition root.

#### Usecase Orchestration

**Где применяется**: `VaultKeyManagementUseCase`.

**Реализация в коде**:
- `init_keyring()`
- `status()`
- `verify_unseal()`
- `rotate_and_rewrap()`
- `rewrap_all_dek()`

**Зачем**: CLI handler остаётся тонким и отвечает только за prompts/options,
а lifecycle-переходы vault живут в usecase layer.

### Диаграмма зависимостей

```text
Typer command
  → command handler
  → CommandContext.container
  → AppContainer
  → SqliteContainer.vault_ready
  → VaultStartupGuard
  → VaultContainer.read/write services

vault-management command
  → VaultAdminPasswordGate
  → prompt unseal passphrase
  → VaultKeyManagementUseCase
  → repository/cipher/unseal service/post verifier
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Где используется |
|-----------|------------|------------------|
| `SecretLocatorPort` | Детерминированно адресует secret по dataset/field/source_ref | write/read services |
| `VaultPostVerifyProtocol` | Проверить vault после init/rotate/rewrap | `VaultKeyManagementUseCase` |
| `VaultUnsealServiceProtocol` | Создать metadata или вывести key | `VaultKeyManagementUseCase` |
| `SecretStoreProtocol` | Записать секреты из pipeline | enrich/import plan |
| `SecretProviderProtocol` | Прочитать секреты для apply | import apply |
| `SecretApplyRetentionHookProtocol` | Реагировать на успешный apply и чистить ephemeral secrets | import apply |

### Port Contracts

#### `SecretLocatorPort`

```python
class SecretLocatorPort(Protocol):
    def build_locator_hash(
        self,
        *,
        dataset: str,
        field: str,
        source_ref: dict | None,
        locator_version: str = "v1",
    ) -> str: ...
```

Контракт locator-а критичен для безопасности и восстановления: write path и
read path обязаны строить один и тот же `locator_hash` из одинакового
`dataset/field/source_ref`. Locator hash не является секретом, но он не должен
раскрывать plaintext `match_key`.

#### `SecretStoreProtocol`

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

Используется enrich/import-plan стадиями. Delivery передаёт protocol в pipeline
только если runtime mode и rollout policy разрешили vault.

#### `SecretProviderProtocol`

```python
class SecretProviderProtocol(Protocol):
    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        source_ref: dict | None = None,
        run_id: str | None = None,
        ...
    ) -> str | None: ...
```

Используется apply adapter-ом. `None` означает "секрет отсутствует или locator
context недостаточен"; ошибки чтения/decrypt считаются блокирующими.

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `SecretLocatorService` | Canonical locator hash | `build_locator_hash()` |
| `SecretVaultWriteService` | Запись plaintext secrets в encrypted vault | `put_many()` |
| `SecretVaultReadService` | Hydration secrets перед apply | `get_secret()` |
| `VaultStartupGuard` | Fail-fast readiness check | `ensure_ready()` |
| `VaultRetentionService` | Очистка ephemeral secrets после apply | `on_apply_success()` |
| `VaultKeyManagementUseCase` | Lifecycle orchestration | `init_keyring()`, `rotate_and_rewrap()`, `rewrap_all_dek()` |
| `VaultStartupGuardPostVerifier` | Adapter usecase → startup guard | `ensure_ready()` |
| `VaultAdminPasswordGate` | Проверка доступа к management commands | `verify_manual_access()` |
| `VaultContainer` | DI sub-container vault services | providers only |

---

## 🗂️ Модели данных

### Dataclass: `VaultKeyManagementStatus`

**Назначение**: read-only snapshot состояния vault для `vault-management status`.

**Lifecycle**:
1. Создаётся usecase-ом из repository state.
2. Delivery превращает его в JSON payload.
3. `status --verify` дополнительно проверяет passphrase и probe.

### Dataclass: `VaultKeyManagementResult`

**Назначение**: результат mutating lifecycle операции.

**Поля результата**:
- operation;
- run_id;
- active_key_version;
- dek_rewrapped_count;
- rotated_at.

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `vault_startup_resource()` | O(Argon2id + probe) | Поднять schema, вывести key, проверить startup probe |
| `VaultKeyManagementUseCase.rotate_and_rewrap()` | O(n DEK) | Сменить passphrase/key version и rewrap-ить DEK |
| `VaultKeyManagementUseCase.init_keyring()` | O(Argon2id + probe) | Атомарно создать unseal metadata и startup probe |
| `SecretLocatorService.build_locator_hash()` | O(n) от размера canonical JSON | Построить стабильный locator hash |
| `SecretVaultWriteService.put_many()` | O(secret fields) | Зашифровать и сохранить secret fields |
| `SecretVaultReadService.get_secret()` | O(key candidates) | Найти, unwrap-ить и decrypt-ить secret |
| `VaultStartupGuard.ensure_ready()` | O(Argon2id уже выполнен + probe decrypt) | Проверить DEK/probe/storage readiness |
| `provide_runtime_unseal_passphrase()` | O(1) | Получить passphrase и передать в AppContainer |

### Метод: `VaultKeyManagementUseCase.init_keyring()`

**Расположение**: `connector/usecases/management/vault/usecase.py`

**Сигнатура**:
```python
def init_keyring(self, *, passphrase: str, run_id: str | None = None) -> VaultKeyManagementResult:
```

**Назначение**: выполнить первичную инициализацию vault в unseal-модели.

**Алгоритм**:
```text
1. Проверить, что vault_unseal_meta ещё нет.
2. Создать metadata и active runtime key через VaultUnsealService.
3. В repository transaction:
   - сохранить vault_unseal_meta;
   - выполнить post_verify.ensure_ready((active_key,)).
4. Если post-verify создаёт DEK/probe и падает, transaction rollback удаляет
   metadata/DEK/probe изменения.
5. После успешной transaction записать rotation metadata result=ok.
```

**Инвариант**: `init` не должен оставлять состояние "metadata есть, probe/DEK
не готовы". Это важно, потому что повторный `init` отвергает уже initialized
vault.

### Метод: `VaultKeyManagementUseCase.rotate_and_rewrap()`

**Расположение**: `connector/usecases/management/vault/usecase.py`

**Сигнатура**:
```python
def rotate_and_rewrap(
    self,
    *,
    current_passphrase: str,
    new_passphrase: str,
    run_id: str | None = None,
) -> VaultKeyManagementResult:
```

**Назначение**: проверить старую passphrase, создать metadata для новой
passphrase, rewrap-ить все DEK новым master wrapping key и выполнить post-verify.

**Алгоритм**:
```text
1. Прочитать текущую unseal metadata.
2. Вывести old key из current_passphrase.
3. Создать new metadata и new key из new_passphrase.
4. В DB transaction:
   - отметить rotation in progress;
   - сохранить new metadata;
   - unwrap каждого DEK старым key;
   - wrap каждого DEK новым key;
   - сохранить обновлённые DEK.
5. Выполнить startup post-verify с новым key.
6. Записать успешный rotation status.
```

**Failure modes**:
- нет metadata → controlled management operation error;
- старая passphrase неверна → HMAC mismatch;
- любой unwrap/wrap/storage сбой → transaction rollback.

### Метод: `SecretLocatorService.build_locator_hash()`

**Расположение**: `connector/domain/secrets/secret_locator_service.py`

**Назначение**: построить stable opaque hash для адресации secret record.

**Алгоритм**:
```text
1. Проверить supported locator_version.
2. Нормализовать dataset, field и source_ref.
3. Собрать canonical JSON с sort_keys и compact separators.
4. Посчитать SHA-256 canonical payload.
5. Вернуть versioned locator hash.
```

**Edge cases**:
- отсутствует `source_ref.match_key` → write path не должен создавать secret;
- read path при недостаточном context возвращает `None`, а не строит случайный locator;
- изменение canonical формата требует новой `locator_version`.

### Метод: `SecretVaultWriteService.put_many()`

**Расположение**: `connector/domain/secrets/secret_vault_write_service.py`

**Алгоритм**:
```text
1. Получить active master key из VaultKeyProviderPort.
2. Найти active DEK или создать новый DEK.
3. Для каждого secret field:
   - построить locator_hash;
   - encrypt plaintext через DEK;
   - сохранить VaultSecretRecord.
4. Storage/crypto ошибки поднять как domain Secret*Error без plaintext leakage.
```

**Side effects**:
- может создать active DEK;
- upsert-ит secret records scoped by dataset/field/locator/run_id;
- не возвращает plaintext наружу.

### Метод: `SecretVaultReadService.get_secret()`

**Расположение**: `connector/domain/secrets/secret_vault_read_service.py`

**Алгоритм**:
```text
1. Нормализовать source_ref.match_key.
2. Построить locator_hash тем же locator version.
3. Прочитать secret record с precedence exact run_id → global NULL.
4. Прочитать DEK по record.dek_version.
5. Unwrap DEK через key candidates.
6. Decrypt ciphertext и вернуть plaintext.
```

**Семантика ошибок**:
- `None`: нет locator context или secret record;
- `SecretReadError`: не найден DEK/storage failure/key config failure;
- `SecretDecryptionError`: DEK не unwrap-ится доступными key candidates;
- `SecretIntegrityError`: ciphertext/token повреждён.

### Метод: `VaultStartupGuard.ensure_ready()`

**Расположение**: `connector/domain/secrets/vault_startup_guard.py`

**Алгоритм**:
```text
1. Получить active master key из provider.
2. Проверить storage readonly через _StorageReadinessProbe.
3. Прочитать startup probe.
4. Если probe отсутствует и storage writable:
   - создать DEK при необходимости;
   - записать encrypted probe.
5. Проверить структуру probe.
6. Unwrap DEK и decrypt probe payload.
7. В strict readonly policy заблокировать запуск на readonly storage.
```

**Почему это отдельный guard**: runtime pipeline должен падать до обработки
строк, если vault не initialized, passphrase неверна, probe повреждён или storage
не соответствует policy.

### Метод: `VaultRetentionService.on_apply_success()`

**Расположение**: `connector/domain/secrets/vault_retention_service.py`

**Назначение**: удалить ephemeral secrets после успешного apply item, если
`secret_lifecycle.delete_on_success=true`.

**Алгоритм**:
```text
1. Проверить lifecycle mode.
2. Для каждого secret field построить locator_hash тем же locator service.
3. Удалить secret record для dataset/field/locator/run_id.
4. Вернуть stats для отчётности.
```

**Важно**: retention не читает plaintext secret и не участвует в decrypt path.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Взаимодействие |
|------|----------------|
| Config | `VaultManagementConfig` хранит admin-gate настройки и путь к hash file |
| Delivery | Typer commands, prompts, command result mapping |
| Usecase | Vault lifecycle orchestration без Typer/ENV/SQLite details |
| Domain | Startup/read/write/retention services через ports |
| Infra | SQLite repository, Fernet cipher, Argon2id/HMAC unseal service |

---

## 🔌 Контракты и границы

- Delivery layer отвечает за prompt и command UX.
- Usecase layer не знает о Typer, ENV, YAML и конкретной SQLite реализации.
- Infra layer реализует KDF/HMAC и SQLite storage.
- `VaultContainer` не читает ENV и не выполняет user prompt.
- `vault-management status` не требует unseal passphrase, если не указан `--verify`.
- `vault-management init/rotate/rewrap` всегда проходят через admin password gate,
  если policy не отключена конфигом.

---

## 💡 Типичные сценарии

1. **Init**
   ```bash
   nexus --config ./config.yml vault-management init --force
   ```
   CLI запрашивает admin password и новую unseal passphrase дважды.

2. **Status без unseal**
   ```bash
   nexus --config ./config.yml vault-management status
   ```
   Показывает metadata/DEK состояние без проверки passphrase.

3. **Status с проверкой**
   ```bash
   nexus --config ./config.yml vault-management status --verify
   ```
   Дополнительно запрашивает unseal passphrase и проверяет startup probe.

4. **Runtime запуск**
   ```bash
   nexus --config ./config.yml enrich
   ```
   Если dataset требует vault, команда запросит unseal passphrase перед startup guard.

5. **Canary rollout**
   ```yaml
   vault_rollout:
     mode: "canary"
     canary_percent: 20
     canary_datasets: ["employees"]
   ```
   `evaluate_vault_rollout()` детерминированно выбирает bucket по
   `canary_seed|dataset|run_id`. Если строка не попадает в canary, command
   возвращает controlled error до startup.

6. **Staging dry-run**
   ```yaml
   vault_rollout:
     mode: "staging_dry_run"
   ```
   Vault path включён, но apply принудительно становится dry-run. Ephemeral
   retention при dry-run не удаляет secrets.

---

## 📌 Важные детали

### 🚨 Failure Modes

| Сценарий | Поведение |
|----------|-----------|
| Admin password hash file отсутствует | management command возвращает config error |
| Hash file имеет group/other permissions | management command fail-closed |
| Vault не initialized | runtime команда fails before pipeline |
| Unseal passphrase неверна | startup/usecase error до чтения пользовательских секретов |
| Rollout policy блокирует vault | command возвращает controlled error до startup |
| Init post-verify падает | metadata/DEK/probe изменения откатываются transaction rollback |
| Read path не нашёл secret | adapter получает `None` и решает, required ли поле |
| Required secret отсутствует | apply item блокируется с диагностикой `SECRET_REQUIRED` |
| Retention delete не прошёл | apply result содержит retention error; plaintext не раскрывается |

### ⚠️ Инварианты системы

- Admin password hash берётся строго из configured hash file.
- Master key не берётся из process ENV и не persisted на диске.
- Runtime passphrase вводится prompt-only в текущей версии.
- `delete-key`, `run-maintenance`, managed env keyring и auto-rotation удалены.
- Dev vault DB можно пересоздать; migration path для managed env keyring не поддерживается.
- `VaultContainer` получает готовый `unseal_passphrase` provider от composition root.
- `vault-management status` без `--verify` не требует unseal passphrase и не decrypt-ит probe.
- `status --verify`, `init`, `rotate`, `rewrap` выполняют post-verify через startup guard.
- Runtime `vault_ready` должен быть initialized до создания read/write services.

### ⏱️ Performance заметки

- `vault_startup_resource()` делает Argon2id derive один раз при runtime startup.
- Mutating management operations выполняют post-verify сразу после изменения.
- Rotate имеет линейную стоимость от количества DEK.
- Locator hash строится только для secret fields и зависит от размера canonical
  `source_ref`, обычно это маленький payload.
- Read path unwrap-ит DEK на каждый secret lookup; при большом количестве lookup
  можно рассмотреть per-run DEK plaintext cache, но только с отдельным security ADR.

### Common Mistakes

| Ошибка | Почему плохо | Как правильно |
|--------|--------------|---------------|
| Вызывать `ctx.container.vault.write_service()` до `vault_ready.init()` | provider может быть создан без проверенного unseal/startup state | сначала `provide_runtime_unseal_passphrase(ctx)`, затем `vault_ready.init()` |
| Строить locator вручную в pipeline | write/read path разойдутся | использовать `SecretLocatorService` |
| Ловить все `Secret*Error` и продолжать apply | можно отправить target payload без required secret | маппить required secret ошибки в blocked item |
| Добавлять ENV input для unseal passphrase | возвращает bypass-поверхность | ввод через prompt-only до отдельного ADR |
| Отключать admin gate через ENV | security-sensitive config не должен меняться окружением | менять только explicit config/CLI policy |

---

## 🛠️ Как расширять

- Новую management-команду добавлять через Typer handler → usecase method, не
  помещая storage/KDF logic в delivery.
- Automation unseal source должен быть отдельным provider input в composition root.
- Для RBAC расширять admin gate/usecase policy отдельно от unseal key derivation.

---

## 🔗 Связанные документы

- [vault-core.md](vault-core.md)
- [vault-crypto.md](vault-crypto.md)
- [vault-storage.md](vault-storage.md)
- [VAULT-DEC-003](../../../adr/vault/VAULT-DEC-003-unseal-derived-master-key-runtime.md)
