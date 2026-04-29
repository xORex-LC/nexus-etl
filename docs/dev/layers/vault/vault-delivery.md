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
| `VaultPostVerifyProtocol` | Проверить vault после init/rotate/rewrap | `VaultKeyManagementUseCase` |
| `VaultUnsealServiceProtocol` | Создать metadata или вывести key | `VaultKeyManagementUseCase` |
| `SecretStoreProtocol` | Записать секреты из pipeline | enrich/import plan |
| `SecretProviderProtocol` | Прочитать секреты для apply | import apply |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
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
| `provide_runtime_unseal_passphrase()` | O(1) | Получить passphrase и передать в AppContainer |

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
   syncEmployees --config ./config.yml vault-management init --force
   ```
   CLI запрашивает admin password и новую unseal passphrase дважды.

2. **Status без unseal**
   ```bash
   syncEmployees --config ./config.yml vault-management status
   ```
   Показывает metadata/DEK состояние без проверки passphrase.

3. **Status с проверкой**
   ```bash
   syncEmployees --config ./config.yml vault-management status --verify
   ```
   Дополнительно запрашивает unseal passphrase и проверяет startup probe.

4. **Runtime запуск**
   ```bash
   syncEmployees --config ./config.yml enrich
   ```
   Если dataset требует vault, команда запросит unseal passphrase перед startup guard.

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

### ⚠️ Инварианты системы

- Admin password hash берётся строго из configured hash file.
- Master key не берётся из process ENV и не persisted на диске.
- Runtime passphrase вводится prompt-only в текущей версии.
- `delete-key`, `run-maintenance`, managed env keyring и auto-rotation удалены.
- Dev vault DB можно пересоздать; migration path для managed env keyring не поддерживается.

### ⏱️ Performance заметки

- `vault_startup_resource()` делает Argon2id derive один раз при runtime startup.
- Mutating management operations выполняют post-verify сразу после изменения.
- Rotate имеет линейную стоимость от количества DEK.

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
