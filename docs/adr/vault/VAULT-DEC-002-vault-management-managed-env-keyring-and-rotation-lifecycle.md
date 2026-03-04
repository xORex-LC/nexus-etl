# VAULT-DEC-002: Vault Management с managed env keyring, rotate+rewrap и policy-driven auto-rotation

> **Статус**: Предложено
> **Дата принятия**: 2026-03-04
> **Решает проблему**: [VAULT-PROBLEM-002](./VAULT-PROBLEM-002-missing-vault-management-and-key-lifecycle-automation.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Текущая Vault-реализация (DEC-001) уже обеспечивает шифрование, keyring parsing и startup readiness, но не предоставляет user-facing lifecycle management ключей.

Нужно закрыть полный операционный контур:
- инициализация keyring для первого запуска;
- безопасная ротация (`rotate + rewrap + verify`);
- автоматическая ротация по YAML-политике;
- ручные операции управления с password gate;
- persisted источник keyring, пригодный для деплоя.

Дополнительно в roadmap есть общий operational контур (`healthcheck`, `VACUUM`, maintenance-задачи), поэтому важно не смешать эксплуатационную orchestration-логику с доменным ядром `domain/secrets`.

---

## 🎯 Решение

Принято реализовать отдельную подсистему **Vault Management** с командным namespace:

`syncEmployees vault-management <subcommand>`

Ключевые решения:
1. Приоритет источников keyring: `ANKEY_VAULT_MASTER_KEYS` (явно заданный runtime env) является главным; managed env-файл используется как persisted fallback/import source.
2. Поддержать команды lifecycle: `init`, `status`, `rotate`, `rewrap`, `delete-key`, `run-maintenance`.
3. Ручные операции защищать **паролем администратора vault** с `argon2id`-хешем (без HashiCorp/AppRole на этом этапе).
4. Включить **non-interactive** режим для автоматических сценариев.
5. Реализовать `ask-confirm` по умолчанию + `--force`.
6. Поддержать **auto-rotation policy** из YAML (часы/дни/месяцы/годы).
7. Всегда выполнять **post-operation verify** через startup guard.
8. Хранить ключевой материал только в env-контуре (managed env-файл), без записи в AppConfig.
9. Размещать operational orchestration в `usecases/operations/*`; `domain/secrets` оставлять только для инвариантов и портов.
10. В новом management-контуре использовать `structlog`; legacy stdlib logging вне scope массовой миграции.
11. `rotate` и `rewrap` выполняются по **всем DEK** в vault-хранилище.
12. Keyring хранит **ровно один активный master key**; после успешного `rotate + rewrap + verify` предыдущий master key не сохраняется.
13. `init` разрешён только при отсутствии активного keyring; повторный `init` должен завершаться контролируемой ошибкой.
14. Любой параметр, доступный для override через CLI/ENV/config, не хардкодится в usecase/domain/infra; дефолты задаются только в CONFIG-слое.
15. В `v1` вводятся только два новых порта (`VaultManagedKeyringStorePort`, `VaultAdminGatePort`); lifecycle metadata интегрируется в существующий `SecretVaultRepositoryPort`, а `VaultRotationPolicy` остаётся domain-service без отдельного порта.
16. `rotate` реализуется как crash-safe двухфазная операция с временным `bridge keyring` (`new,old`) и обязательной финализацией в single-key steady-state.

Определения:
- `run-maintenance` — non-interactive operational entrypoint для policy-задач (`is_due`, rotate + rewrap + verify, metadata update).
- `single-active-keyring` — steady-state политика хранения только одного active master key в effective keyring.
- `bridge keyring` — временное состояние keyring (`new,old`) во время in-flight `rotate`; после успешной финализации запрещено.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `VaultManagementConfig` (`connector/config/models.py`) — policy управления ротацией и security-gate.
- `VaultRotationPolicy` (`connector/domain/secrets/policy/rotation_policy.py`) — доменные правила вычисления `rotation due?`.
- `VaultManagedEnvKeyringStore` (`connector/infra/secrets/management/managed_env_keyring_store.py`) — чтение/запись managed env keyring.
- `VaultAdminPasswordGate` (`connector/infra/secrets/management/admin_password_gate.py`) — verify admin password для manual operations.
- `VaultKeyManagementUseCase` (`connector/usecases/operations/vault_key_management.py`) — orchestration `init/rotate/rewrap/delete/status`.
- `VaultMaintenanceUseCase` (`connector/usecases/operations/vault_maintenance.py`) — non-interactive policy-driven maintenance.
- `vault_management` delivery command (`connector/delivery/commands/vault_management.py`) + wiring в CLI.

**Изменения в существующих компонентах**:
- `AppConfig` расширяется секцией `vault_management`.
- В `vault` SQLite добавляется служебная таблица `vault_management_meta` (в той же DB), где хранится lifecycle metadata (`last_rotated_at`, `last_rotation_result`, `last_rotation_reason` и т.п.).
- Существующий `SecretVaultRepositoryPort` расширяется методами работы с lifecycle metadata (без выделения отдельного meta-port).
- SQLite-реализация существующего vault repository реализует lifecycle metadata-методы в текущем репозитории.
- `vault_startup_resource()` дополняется preflight: загрузка managed env keyring и optional auto-maintenance через `VaultMaintenanceUseCase`.
- `VaultStartupGuard` переиспользуется как post-verify шаг после lifecycle-операций.

### Границы ответственности

- `domain/secrets/*`: только инварианты, policy, domain-порты и domain-ошибки (без prompt/env/file/schedule orchestration).
- `usecases/operations/*`: сценарии выполнения operational задач (`vault management`, `check-api health`, `sqlite vacuum` и т.п.).
- `infra/secrets/management/*` и `infra/operations/*`: конкретные адаптеры для IO/security/executor.
- `delivery/commands/*`: CLI boundary (аргументы, confirm/prompt, формат вывода).

### Интерфейсы

```python
class VaultManagedKeyringStorePort(Protocol):
    def load_keyring(self) -> tuple[VaultMasterKey, ...]: ...
    def save_keyring(self, keys: tuple[VaultMasterKey, ...], *, force: bool) -> None: ...


class VaultAdminGatePort(Protocol):
    def verify_manual_access(self, *, non_interactive: bool) -> None: ...

class VaultKeyManagementUseCase:
    def init_keyring(self, *, force: bool) -> None: ...
    def rotate_and_rewrap(self, *, force: bool) -> str: ...
    def rewrap_all_dek(self) -> None: ...
    def delete_key(self, *, force: bool) -> None: ...


class VaultMaintenanceUseCase:
    def run_if_due(self, *, non_interactive: bool, force: bool) -> bool: ...
```

```python
class SecretVaultRepositoryPort(Protocol):
    # ... существующие методы secrets/DEK/startup probe
    def get_last_rotated_at(self) -> str | None: ...
    def set_last_rotated_at(self, iso_utc: str) -> None: ...
    def set_last_rotation_result(self, *, result: str, reason: str | None = None) -> None: ...
```

### Поток данных

```
Manual rotate:
CLI vault-management rotate
  -> VaultAdminGate.verify_manual_access()
  -> VaultKeyManagementUseCase.rotate_and_rewrap()
  -> load managed env keyring
  -> generate new Fernet key as next active
  -> persist bridge keyring (new,old)
  -> rewrap all DEK with new active key
  -> persist final keyring (new only)
  -> VaultStartupGuard.ensure_ready()   (post-verify)

Auto-maintenance:
vault_startup_resource()
  -> load managed env keyring into process env
  -> VaultMaintenanceUseCase.run_if_due(non-interactive)
  -> evaluate rotation policy (due / not due)
  -> if due: VaultKeyManagementUseCase.rotate_and_rewrap()
  -> if not due: no-op (successful completion)
  -> VaultStartupGuard.ensure_ready()
```

### Source Precedence (env-first)

```
1. if os.environ["ANKEY_VAULT_MASTER_KEYS"] is set and non-empty:
       use it as effective keyring
2. else:
       load keyring from managed env-file
       export to process env as ANKEY_VAULT_MASTER_KEYS
```

Это сохраняет текущий runtime-контракт `EnvVaultKeyProvider` и позволяет деплой-операторам явно переопределять keyring через process env.

### Legacy migration (`--import-existing-env`)

One-shot сценарий:
1. Проверить, что managed env-файл отсутствует или пуст.
2. Прочитать и валидировать текущий `ANKEY_VAULT_MASTER_KEYS`.
3. Сохранить keyring в managed env-файл атомарно.
4. Записать `vault_management_meta` (`last_rotation_result=ok`, `last_rotation_reason=import_existing_env`).
5. Выполнить post-verify (`VaultStartupGuard.ensure_ready()`).

Повторный запуск без `--force`:
- завершается контролируемой ошибкой `already_initialized`.

### Persistency and Locking

- Запись managed env-файла: `tmp file -> fsync(file) -> rename -> fsync(dir)`; права `0600`.
- Межпроцессная сериализация lifecycle-команд: `flock` на managed env-файле.
- Консистентность rewrap-операций: SQLite `BEGIN IMMEDIATE` в vault DB.

### Vault-management metadata (в той же vault DB)

Таблица `vault_management_meta` (key-value):
- `last_rotated_at` (ISO UTC)
- `last_rotation_result` (`ok|failed|skipped_due`)
- `last_rotation_reason` (машиночитаемая причина)
- `last_rotation_run_id` (опционально)

Причина выбора той же DB:
- metadata и DEK lifecycle обновляются в одном transaction scope;
- нет рассинхронизации между отдельными storage-контурами.

### Транзакционная граница lifecycle-операций

`rotate` (crash-safe двухфазный протокол):
1. Взять `flock`.
2. Прочитать текущий keyring (`old` active key обязателен).
3. Сгенерировать `new` active key.
4. Атомарно записать `bridge keyring` (`new,old`) в managed env-файл.
5. Открыть SQLite transaction (`BEGIN IMMEDIATE`).
6. Выполнить rewrap всех DEK на `new` + update `vault_management_meta` (`result=rotating` / `run_id`).
7. Завершить DB transaction.
8. Атомарно записать финальный keyring (`new` only) в managed env-файл.
9. Обновить `vault_management_meta` (`result=ok`, `last_rotated_at`).
10. Выполнить `VaultStartupGuard.ensure_ready()` (post-verify).

`rewrap`:
1. Взять `flock`.
2. Открыть SQLite transaction (`BEGIN IMMEDIATE`).
3. Выполнить rewrap всех DEK текущим active key + update `vault_management_meta`.
4. Завершить DB transaction.
5. Выполнить `VaultStartupGuard.ensure_ready()` (post-verify).

Failure semantics:
- если операция прерывается до шага `8` в `rotate`, система остаётся в recoverable состоянии (`bridge keyring` позволяет decrypt старых и новых DEK);
- `run-maintenance` обязан обнаруживать in-flight bridge и выполнять safe-finalization (или fail-fast по `auto_rotate_on_error`);
- если verify не проходит, операция считается `failed`, фиксируется в meta, runtime завершается fail-fast.

### Конфигурация auto-rotation

```python
class VaultRotationIntervalConfig(BaseModel):
    hours: int = 0
    days: int = 0
    months: int = 0
    years: int = 0


class VaultManagementConfig(BaseModel):
    managed_env_file: str | None = None
    require_admin_password_for_manual_ops: bool = True
    admin_password_hash_env_var: str = "ANKEY_VAULT_ADMIN_PASSWORD_HASH"
    admin_password_env_var: str = "ANKEY_VAULT_ADMIN_PASSWORD"
    auto_rotate_enabled: bool = False
    auto_rotate_interval: VaultRotationIntervalConfig = VaultRotationIntervalConfig(days=30)
    auto_rotate_on_error: Literal["fail_closed", "fail_open"] = "fail_closed"
```

Валидация (Pydantic):
- `auto_rotate_interval`: хотя бы одно поле (`hours|days|months|years`) должно быть > 0.
- Все значения интервала должны быть `>= 0`.
- Расчёт due-window выполняется в UTC; `months/years` считаются календарно.

### CLI сценарии и идемпотентность

| Команда | Назначение | Идемпотентность | Ошибка/ограничение |
|---------|------------|-----------------|--------------------|
| `vault-management init` | Создать первый keyring | Не идемпотентна (one-time) | Падает, если активный keyring уже существует |
| `vault-management status` | Показать состояние lifecycle | Идемпотентна (read-only) | Падает при повреждённом keyring/meta |
| `vault-management rotate` | Создать новый active key + rewrap всех DEK + verify | Не идемпотентна (создаёт новую версию ключа) | Не зависит от due-политики, выполняется по явному запросу |
| `vault-management rewrap` | Rewrap всех DEK текущим active key + verify | Идемпотентна при неизменном active key | Падает, если отсутствует active key |
| `vault-management delete-key` | Заменить текущий active key через replace-flow | Не идемпотентна (создаёт новую версию ключа) | Прямое удаление единственного active key запрещено |
| `vault-management run-maintenance` | Выполнить auto-policy задачи | Идемпотентна при `due=false` | Поведение ошибок (в т.ч. readonly storage при due) определяется `auto_rotate_on_error` |

Пояснение по due:
- due-проверка относится только к `run-maintenance`.
- Ручной `rotate` не блокируется due-политикой.

### CLI флаги и управляемые параметры

Общие флаги operational-команд:
- `--force`: отключает только confirm-step; safety-checks и verify остаются обязательными.
- `--dry-run`: не записывает изменения в keyring/DB, но выполняет валидацию и план действий.
- `--non-interactive`: отключает prompt-взаимодействие; пароль берётся из env.
- `--verify/--no-verify`: post-operation startup verification (`VaultStartupGuard.ensure_ready()`).
- `--managed-env-file <path>`: переопределение пути managed env-файла для вызова.

Специальные флаги:
- `init --import-existing-env`: one-shot миграция существующего `ANKEY_VAULT_MASTER_KEYS` в managed env-file.

### Config/ENV/CLI контракт (Settings layer)

Единый путь (как в CONFIG-layer): `CLI > ENV > config.yml > defaults`.

Пример секции в `config.yml`:

```yaml
vault_management:
  managed_env_file: "./cache/vault.env"
  require_admin_password_for_manual_ops: true
  admin_password_hash_env_var: "ANKEY_VAULT_ADMIN_PASSWORD_HASH"
  admin_password_env_var: "ANKEY_VAULT_ADMIN_PASSWORD"
  auto_rotate_enabled: true
  auto_rotate_interval:
    days: 30
  auto_rotate_on_error: "fail_closed"
```

ENV override-паттерн:
- `ANKEY_VAULT_MANAGEMENT__MANAGED_ENV_FILE`
- `ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_ENABLED`
- `ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_INTERVAL`
- `ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_ON_ERROR`
- `ANKEY_VAULT_MANAGEMENT__REQUIRE_ADMIN_PASSWORD_FOR_MANUAL_OPS`

Формат `ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_INTERVAL`:
- строка вида `hours=0,days=30,months=0,years=0`;
- парсинг выполняется в `field_validator` Pydantic-модели.

Идемпотентное прокидывание настроек:
1. `load_app_config()` формирует immutable `AppConfig`.
2. projection в typed settings для `usecases/operations`.
3. use-case получает settings snapshot per invocation (без глобального mutable state).

Правило anti-hardcode:
1. Параметры, поддерживающие override через CLI/ENV/config, имеют дефолты только в `connector/config/*`.
2. `usecases/*`, `domain/*`, `infra/*` получают уже разрешённые значения и не назначают fallback-defaults.
3. Нарушение правила считается архитектурным дефектом и покрывается architecture-тестом.

### Security и Observability профиль (v1)

`argon2id` параметры (default v1):
- `time_cost=3`
- `memory_cost_kib=65536`
- `parallelism=2`
- `hash_len=32`

Политика секретов:
- в логах/ошибках запрещены: plaintext секретов, key material, admin password, password hash.
- допустимы только служебные поля: `key_version`, `dek_version`, `reason`, `result`, `run_id`.

Права managed env-файла:
- целевое состояние: `0600`;
- enforce при записи;
- drift detection на старте (если права шире — fail-fast с диагностикой).

Невозможно полностью запретить смену прав для привилегированного пользователя ОС;
контур обеспечивает детекцию и блокировку запуска при небезопасном состоянии.

`structlog` event taxonomy для нового кода:
- `event`: `vault_mgmt_init|vault_mgmt_rotate|vault_mgmt_rewrap|vault_mgmt_delete|vault_mgmt_maintenance`
- `op`: `start|success|failed|skipped_due`
- `component`: `vault_management`
- `run_id`, `key_version`, `result`, `reason`, `error_code`

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Закрывает полный lifecycle master keys в рамках существующей архитектуры DEC-001.
- ✅ Даёт deterministic и воспроизводимый путь ротации (`rotate + rewrap + verify`).
- ✅ Упрощает деплой: managed env-файл можно централизованно распространять и версионировать операционно.
- ✅ Поддерживает и ручной режим, и автоматический non-interactive maintenance.
- ✅ Не требует немедленного перехода на внешний KMS/Transit.

**Недостатки (компромиссы)**:
- ⚠️ Managed env-файл остаётся чувствительным артефактом и требует строгих прав доступа.
- ⚠️ Password gate защищает операции CLI, но не заменяет HSM/KMS-модель хранения ключей.
- ⚠️ Auto-rotation выполняется на startup/maintenance-path (не daemon), что зависит от частоты запусков.
- ⚠️ Политика `fail_closed` при авто-ротации может блокировать команду при временных IO/lock сбоях (безопасность приоритетнее доступности).
- ⚠️ В single-key steady-state нет persisted fallback master key, поэтому ротация требует crash-safe протокола и строгого verify/fail-fast контура.

**Альтернативы, которые отклонили**:
- ❌ **Docs-only/manual runbook**: не снижает риск human error в production.
- ❌ **Только keygen без rotate/rewrap**: не закрывает критичный lifecycle gap.
- ❌ **Сразу внешний Vault Transit/KMS**: существенно увеличивает scope из-за auth/integration ops.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/config/models.py` | Добавить `VaultManagementConfig` и `VaultRotationIntervalConfig` |
| `connector/config/projections.py` | Добавить projection в доменные settings vault-management |
| `connector/delivery/cli/app.py` | Добавить namespace `vault-management` и subcommands |
| `connector/delivery/commands/vault_management.py` | Реализовать user-facing команды управления lifecycle |
| `connector/delivery/cli/containers.py` | Wiring сервисов key-management + startup maintenance hook |
| `connector/domain/secrets/policy/rotation_policy.py` | Доменная логика вычисления due-window |
| `connector/usecases/operations/vault_key_management.py` | Operational orchestration init/rotate/rewrap/delete/status |
| `connector/usecases/operations/vault_maintenance.py` | Policy-driven non-interactive maintenance |
| `connector/infra/secrets/management/managed_env_keyring_store.py` | Persist/load keyring в managed env-файл |
| `connector/infra/secrets/management/admin_password_gate.py` | Manual access gate (prompt/env verify) |
| `connector/domain/ports/secrets/repository.py` | Расширить существующий контракт lifecycle metadata-методами |
| `connector/infra/secrets/sqlite/schema.py` | Добавить `vault_management_meta` в той же vault DB |
| `connector/infra/secrets/sqlite/repository.py` | Реализовать lifecycle metadata-методы в существующем vault repository |
| `pyproject.toml` | Добавить зависимость для `argon2id` (например, `argon2-cffi`) |

### Ключевые методы

- `VaultKeyManagementUseCase.rotate_and_rewrap()` — атомарная ротация ключа и переобёртка всех DEK.
- `VaultKeyManagementUseCase.rewrap_all_dek()` — переобёртка всех DEK текущим active key без генерации нового master key.
- `VaultKeyManagementUseCase.delete_key()` — replace-flow (создать новый активный ключ -> rewrap -> verify -> удалить предыдущий).
- `VaultRotationPolicy.is_due()` — проверка политики (hours/days/months/years).
- `VaultMaintenanceUseCase.run_if_due()` — policy gate для auto-maintenance.
- `vault_startup_resource()` — preflight managed env load + optional auto-maintenance + verify.

### Инварианты

1. Keyring содержит ровно один active master key в steady-state (совместимо с `EnvVaultKeyProvider`).
2. `rotate` всегда включает `rewrap` всех DEK и `post-verify`.
3. Keyring-персистенс выполняется только в managed env-файл (env-only policy).
4. Ручные lifecycle-операции требуют password gate (если policy не отключена).
5. `ask-confirm` обязателен для destructive-операций; `--force` отключает только confirm-step.
6. Любая неуспешная verify-проверка после lifecycle-операции считается failed и завершает сценарий fail-fast (без silent-success).
7. Key material не попадает в исключения, логи, diagnostics details.
8. `domain/secrets` не содержит operational orchestration (prompt, schedule, file IO, command choreography).
9. `delete-key` не удаляет единственный/active ключ напрямую: используется replace-flow с предварительным созданием нового active ключа.
10. При авто-ротации default-политика ошибки `fail_closed`: команда с `requires_vault_init` завершается fail-fast.
11. Параметры override-контракта не хардкодятся в runtime/usecase/domain/infra; дефолты задаются только в CONFIG-слое.
12. `bridge keyring` (`new,old`) допустим только как in-flight состояние `rotate` под `flock`; после успешной операции steady-state обязан вернуться к single-key.

---

## 🧪 Валидация решения

### Структура тестов

Тесты размещаются по правилу:
- `tests/<test_type>/<layer>/...`

Для данного решения:
- unit: `tests/unit/secrets/`, `tests/unit/usecases/operations/`, `tests/unit/config/`
- integration: `tests/integration/secrets/`, `tests/integration/delivery/`
- architecture: `tests/architecture/`
- performance: `tests/performance/vault/` (на `pyperf`)

**Тесты**:
- ✅ Unit: `managed_env_keyring_store` (parse/save, confirm/force, permissions).
- ✅ Unit: `vault_admin_password_gate` (`argon2id`, interactive/non-interactive success/failure, retries).
- ✅ Unit: `rotation_policy` (due/not-due для hours/days/months/years).
- ✅ Integration: `vault-management init` на чистом окружении + `VaultStartupGuard.ensure_ready()`.
- ✅ Integration: `vault-management rotate` выполняет rewrap и сохраняет decrypt-совместимость.
- ✅ Integration: interrupted `rotate` между `bridge keyring` и finalization остаётся recoverable, а `run-maintenance` корректно завершает финализацию (или fail-fast по policy).
- ✅ Integration: `VaultMaintenanceUseCase` в startup path запускает rotation при due-policy.
- ✅ Integration: `--import-existing-env` выполняет one-shot миграцию существующего `ANKEY_VAULT_MASTER_KEYS` в managed env-file.

### Matrix тесты параметров (CLI/ENV/config/defaults)

Для каждого управляемого параметра обязательны tests на:
1. default value (без override)
2. override через `config.yml`
3. override через ENV
4. override через CLI
5. проверку приоритета `CLI > ENV > config.yml > defaults`
6. проверку отсутствия скрытого переопределения в коде runtime/usecase

Параметры для matrix:
- `managed_env_file`
- `require_admin_password_for_manual_ops`
- `admin_password_hash_env_var`
- `admin_password_env_var`
- `auto_rotate_enabled`
- `auto_rotate_interval`
- `auto_rotate_on_error`
- командные флаги: `--force`, `--dry-run`, `--non-interactive`, `--verify`, `--managed-env-file`

### Нагрузочные тесты (pyperf)

- Использовать `pyperf` как обязательный инструмент для performance-кейсов.
- Минимальный набор:
  - rotate/rewrap latency на N DEK;
  - maintenance no-op latency (`due=false`);
  - startup overhead с enabled policy.
- Размещение: `tests/performance/vault/`.

**Проверка в production**:
1. Настроить `vault_management.managed_env_file` и `vault_management.auto_rotate_*` политику.
2. Выполнить `syncEmployees vault-management init --verify`.
3. Выполнить `syncEmployees vault-management rotate --verify` на staging.
4. Проверить, что `import plan/apply/enrich` проходят startup guard после ротации.

**Метрики успеха**:
- Ошибки `VAULT_STARTUP_KEY_CONFIG_ERROR(reason=empty_keyring)` для новых инсталляций должны стремиться к 0.
- Ручные keyring-инциденты при ротации (потеря active key / несовместимость после rewrap) должны исчезнуть.

---

## 📐 Диаграммы

**UML диаграммы** (будут добавлены отдельно при реализации):
- Class: `operations/vault-management` usecase + domain policy + infra adapters.
- Sequence: `rotate + rewrap + verify`.

**Примеры использования**:

```bash
# Инициализация keyring
syncEmployees vault-management init --verify

# Ручная ротация (с confirm)
syncEmployees vault-management rotate --verify

# Non-interactive maintenance по policy
syncEmployees vault-management run-maintenance --non-interactive --force
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Managed env-файл не обновляет env родительского shell автоматически; он является persisted source, который приложение должно явно подгружать.
- Password gate — операционный контроль доступа, а не криптографическая изоляция master keys.

**Риски**:
- ⚠️ Некорректные права на managed env-файл могут привести к утечке key material.
  - **Митигация**: enforce `0600`, fail-fast при слишком широких правах.
- ⚠️ Ошибки в policy-конфигурации (слишком частая ротация) могут увеличить операционную нагрузку.
  - **Митигация**: валидация конфигурации и dry-run режим maintenance.
- ⚠️ Одновременный запуск нескольких процессов может вызвать гонки при rotate/save.
  - **Митигация**: file lock + SQLite transaction boundary на lifecycle-операции.
- ⚠️ Неконсистентный лог-контур в новом management-пути может усложнить диагностику.
  - **Митигация**: в новом коде использовать `structlog` c фиксированными полями (`event`, `op`, `component`, `run_id`, `key_version`, `result`, `reason`).

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/cli/app.py` | Новая командная группа | Добавить `vault-management` namespace |
| `delivery/commands/*` | Косвенное | Вызывают usecases из `operations` вместо domain orchestration |
| `usecases/operations/*` | Прямое | Новый operational-срез для lifecycle, healthcheck, maintenance |
| `config/models.py` | Прямое | Добавить секцию `vault_management` |
| `infra/secrets/env_key_provider.py` | Косвенное | Продолжает использовать `ANKEY_VAULT_MASTER_KEYS`, но источник теперь managed env-file |
| `domain/ports/secrets/repository.py` | Прямое | Расширить существующий репозиторный контракт lifecycle metadata-методами |
| `infra/secrets/sqlite/*` | Прямое | Добавить служебные metadata таблицы vault-management в ту же vault DB |
| `domain/secrets/vault_startup_guard.py` | Косвенное | Используется как verify после lifecycle-операций; orchestration остаётся вне domain |

---

## 📚 Документация

**Обновлена документация**:
- ⏳ `docs/dev/layers/vault/vault-delivery.md` — будет добавлена секция `vault-management`.
- ⏳ `docs/dev/layers/vault/vault-crypto.md` — будет добавлен lifecycle flow `rotate + rewrap + auto-maintenance`.
- ⏳ `README.md` — будет добавлен user guide для `vault-management`.

---

## 🔗 Связанные документы

- [VAULT-PROBLEM-002](./VAULT-PROBLEM-002-missing-vault-management-and-key-lifecycle-automation.md)
- [VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)
- [vault-crypto.md](../../dev/layers/vault/vault-crypto.md)
- [vault-delivery.md](../../dev/layers/vault/vault-delivery.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-04 | Решение предложено по итогам архитектурного обсуждения lifecycle master keys |
| 2026-03-04 | Подтверждён `env-first` контракт: runtime env как effective источник, managed env-файл как persisted fallback/import source |
| 2026-03-04 | Уточнена single-active-keyring модель (без persisted fallback master keys) и anti-hardcode правило для override-параметров |
| 2026-03-04 | Принят lean-подход по портам: удалён `VaultRotationPolicyPort`, metadata встроена в существующий `SecretVaultRepositoryPort` |
