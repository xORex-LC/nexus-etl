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
1. Использовать **managed env-файл** как source-of-truth keyring.
2. Поддержать команды lifecycle: `init`, `status`, `rotate`, `rewrap`, `delete-key`, `run-maintenance`.
3. Ручные операции защищать **паролем администратора vault** (без HashiCorp/AppRole на этом этапе).
4. Включить **non-interactive** режим для автоматических сценариев.
5. Реализовать `ask-confirm` по умолчанию + `--force`.
6. Поддержать **auto-rotation policy** из YAML (часы/дни/месяцы/годы).
7. Всегда выполнять **post-operation verify** через startup guard.
8. Хранить ключевой материал только в env-контуре (managed env-файл), без записи в AppConfig.
9. Размещать operational orchestration в `usecases/operations/*`; `domain/secrets` оставлять только для инвариантов и портов.

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
    def metadata(self) -> dict[str, str]: ...
    def save_metadata(self, metadata: dict[str, str], *, force: bool) -> None: ...


class VaultAdminGatePort(Protocol):
    def verify_manual_access(self, *, non_interactive: bool) -> None: ...


class VaultRotationPolicyPort(Protocol):
    def is_due(self, *, last_rotated_at: str | None, now_utc: str) -> bool: ...


class VaultKeyManagementUseCase:
    def init_keyring(self, *, force: bool) -> None: ...
    def rotate_and_rewrap(self, *, force: bool) -> str: ...
    def rewrap_active_dek(self) -> None: ...
    def delete_key(self, key_version: str, *, force: bool) -> None: ...


class VaultMaintenanceUseCase:
    def run_if_due(self, *, non_interactive: bool, force: bool) -> bool: ...
```

### Поток данных

```
Manual rotate:
CLI vault-management rotate
  -> VaultAdminGate.verify_manual_access()
  -> VaultKeyManagementUseCase.rotate_and_rewrap()
  -> load managed env keyring
  -> generate new Fernet key + prepend active version
  -> rewrap active DEK with new active key
  -> persist updated keyring
  -> VaultStartupGuard.ensure_ready()   (post-verify)

Auto-maintenance:
vault_startup_resource()
  -> load managed env keyring into process env
  -> VaultMaintenanceUseCase.run_if_due(non-interactive)
  -> evaluate rotation policy (due / not due)
  -> if due: VaultKeyManagementUseCase.rotate_and_rewrap()
  -> VaultStartupGuard.ensure_ready()
```

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
    retain_previous_keys: int = 2
```

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

### Ключевые методы

- `VaultKeyManagementUseCase.rotate_and_rewrap()` — атомарная ротация ключа и переобёртка активного DEK.
- `VaultKeyManagementUseCase.rewrap_active_dek()` — переобёртка активного DEK без генерации нового master key.
- `VaultRotationPolicy.is_due()` — проверка политики (hours/days/months/years).
- `VaultMaintenanceUseCase.run_if_due()` — policy gate для auto-maintenance.
- `vault_startup_resource()` — preflight managed env load + optional auto-maintenance + verify.

### Инварианты

1. Первый ключ в keyring всегда активный (совместимо с `EnvVaultKeyProvider`).
2. `rotate` всегда включает `rewrap` активного DEK и `post-verify`.
3. Keyring-персистенс выполняется только в managed env-файл (env-only policy).
4. Ручные lifecycle-операции требуют password gate (если policy не отключена).
5. `ask-confirm` обязателен для destructive-операций; `--force` отключает только confirm-step.
6. Любая неуспешная verify-проверка после lifecycle-операции считается rollback/fail.
7. Key material не попадает в исключения, логи, diagnostics details.
8. `domain/secrets` не содержит operational orchestration (prompt, schedule, file IO, command choreography).

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: `managed_env_keyring_store` (parse/save, confirm/force, permissions).
- ✅ Unit: `vault_admin_password_gate` (interactive/non-interactive success/failure).
- ✅ Unit: `rotation_policy` (due/not-due для hours/days/months/years).
- ✅ Integration: `vault-management init` на чистом окружении + `VaultStartupGuard.ensure_ready()`.
- ✅ Integration: `vault-management rotate` выполняет rewrap и сохраняет decrypt-совместимость.
- ✅ Integration: `VaultMaintenanceUseCase` в startup path запускает rotation при due-policy.

**Проверка в production**:
1. Настроить `vault_management.managed_env_file` и `vault_management.auto_rotate_*` политику.
2. Выполнить `syncEmployees vault-management init --verify`.
3. Выполнить `syncEmployees vault-management rotate --verify` на staging.
4. Проверить, что `import plan/apply/enrich` проходят startup guard после ротации.

**Метрики успеха**:
- Ошибки `VAULT_STARTUP_KEY_CONFIG_ERROR(reason=empty_keyring)` для новых инсталляций должны стремиться к 0.
- Ручные keyring-инциденты при ротации (невалидный порядок/потеря fallback) должны исчезнуть.

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

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `delivery/cli/app.py` | Новая командная группа | Добавить `vault-management` namespace |
| `delivery/commands/*` | Косвенное | Вызывают usecases из `operations` вместо domain orchestration |
| `usecases/operations/*` | Прямое | Новый operational-срез для lifecycle, healthcheck, maintenance |
| `config/models.py` | Прямое | Добавить секцию `vault_management` |
| `infra/secrets/env_key_provider.py` | Косвенное | Продолжает использовать `ANKEY_VAULT_MASTER_KEYS`, но источник теперь managed env-file |
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
| 2026-03-04 | Подтверждён выбор managed env-файла как persisted source-of-truth для keyring |
