# Vault Layer — Delivery: Доменные сервисы, политики и DI

> **Область охвата:** Этот документ описывает оркестрационный слой подсистемы vault —
> доменные сервисы, координирующие поиск, запись, чтение и очистку
> секретов, модули политик, управляющие активацией vault, и подключение DI-контейнера.
>
> **Связанные документы:**
> - [vault-core.md](vault-core.md) — поток домена конвейера (enrich → plan → apply)
> - [vault-crypto.md](vault-crypto.md) — конвертное шифрование, жизненный цикл DEK, Fernet
> - [vault-storage.md](vault-storage.md) — схема SQLite, репозиторий, транзакции

---

## 1. Обзор

Delivery-слой отвечает за оркестрацию операций vault на уровне доменных
сервисов. Он соединяет crypto-слой (шифры, ключи) с storage-слоем
(репозиторий) через чистые интерфейсы доменных сервисов.

### Компоненты этого слоя

| Компонент | Файл | Роль |
|-----------|------|------|
| `SecretLocatorService` | `connector/domain/secrets/secret_locator_service.py` | Построение детерминированного locator hash для адресации секретов |
| `SecretVaultWriteService` | `connector/domain/secrets/secret_vault_write_service.py` | Путь записи: шифрование и сохранение секретов |
| `SecretVaultReadService` | `connector/domain/secrets/secret_vault_read_service.py` | Путь чтения: загрузка и расшифровка секретов |
| `VaultStartupGuard` | `connector/domain/secrets/vault_startup_guard.py` | Быстрая проверка при запуске (fail-fast) |
| `VaultRetentionService` | `connector/domain/secrets/vault_retention_service.py` | Жизненный цикл / очистка после apply |
| `normalize_secret_lifecycle()` | `connector/domain/secrets/policy/retention_policy.py` | Нормализация конфигурации политики retention |
| `resolve_vault_runtime_mode()` | `connector/domain/secrets/policy/runtime_mode_policy.py` | Определение необходимости vault для запуска |
| `evaluate_vault_rollout()` | `connector/domain/secrets/policy/rollout_policy.py` | Поэтапное ограничение rollout в продакшене |
| `build_vault_operational_metrics()` | `connector/domain/secrets/policy/rollout_metrics.py` | Вычисление метрик для принятия решений об откате |
| `VaultContainer` | `connector/delivery/cli/containers.py` | DI-подключение всех компонентов vault |
| `vault_startup_resource()` | `connector/delivery/cli/containers.py` | Жизненный цикл ресурса: схема + guard |

---

## 2. Port Contracts (Delivery-Relevant)

### 2.1 `SecretLocatorPort`

**Файл:** [`connector/domain/ports/secrets/locator.py`](../../../../connector/domain/ports/secrets/locator.py)

```python
class SecretLocatorPort(Protocol):
    def build_locator_hash(
        self, *, dataset: str, field: str, source_ref: dict | None,
        locator_version: str = "v1"
    ) -> str: ...

    def supported_versions(self) -> tuple[str, ...]: ...
```

**Инварианты:**
- Одинаковый входной набор всегда даёт одинаковый hash (детерминированность).
- `locator_version` является частью контракта — должна храниться вместе с hash
  в записи vault для будущей безопасной миграции на новый алгоритм локатора.

### 2.2 `SecretStoreProtocol`

**Файл:** [`connector/domain/ports/secrets/provider.py`](../../../../connector/domain/ports/secrets/provider.py)

```python
class SecretStoreProtocol(Protocol):
    def put_many(
        self, *, dataset: str, match_key: str,
        secrets: dict[str, str], run_id: str | None = None
    ) -> None: ...
```

Реализуется `SecretVaultWriteService`. Вызывается этапом обогащения (enrich), когда
датасет содержит поля с `requires_vault=True`.

### 2.3 `SecretProviderProtocol`

```python
class SecretProviderProtocol(Protocol):
    def get_secret(
        self, *, dataset: str, field: str, row_id: str | None = None,
        line_no: int | None = None, source_ref: dict | None = None,
        target_id: str | None = None, run_id: str | None = None,
    ) -> str | None: ...
```

Реализуется `SecretVaultReadService`. Вызывается этапом apply для гидрации
секретов в полезную нагрузку запросов.

### 2.4 `SecretApplyRetentionHookProtocol`

**Файл:** [`connector/domain/ports/secrets/retention.py`](../../../../connector/domain/ports/secrets/retention.py)

```python
class SecretApplyRetentionHookProtocol(Protocol):
    def on_apply_success(
        self, *, dataset: str, op: str, source_ref: dict | None,
        secret_fields: list[str], secret_lifecycle: dict | None,
        run_id: str | None,
    ) -> Mapping[str, int]: ...

    def run_maintenance(self) -> Mapping[str, int]: ...
```

Реализуется `VaultRetentionService`. Вызывается после каждого успешного вызова
целевого API во время этапа apply.

---

## 3. `SecretLocatorService` — Детерминированная адресация

**Файл:** [`connector/domain/secrets/secret_locator_service.py`](../../../../connector/domain/secrets/secret_locator_service.py)

### 3.1 Алгоритм Locator v1

Сервис локатора строит стабильный, детерминированный адрес для любого секрета в vault.
Адрес (hash) однозначно идентифицирует тройку `(dataset, field, source_ref)`.

```
locator_hash = sha256("<locator_version>|<dataset>|<field>|<canonical_source_ref_json>")
```

**Пример:**
```
Входные данные:
  dataset       = "hr"
  field         = "password"
  source_ref    = {"match_key": "emp_001", "dept": ""}
  locator_version = "v1"

canonical_source_ref_json:
  Шаг 1: _normalize_mapping({"match_key": "emp_001", "dept": ""})
          → пропустить пустые строки → {"match_key": "emp_001"}
  Шаг 2: json.dumps({"match_key": "emp_001"}, sort_keys=True, separators=(",", ":"))
          → '{"match_key":"emp_001"}'

payload = "v1|hr|password|{\"match_key\":\"emp_001\"}"
locator_hash = sha256(payload.encode("utf-8")).hexdigest()
```

### 3.2 Нормализация канонического JSON

**Файл:** [`connector/domain/secrets/secret_locator_service.py:45`](../../../../connector/domain/secrets/secret_locator_service.py#L45)

Нормализация удаляет «пустые» значения перед JSON-сериализацией, чтобы
необязательные поля без значения не изменяли hash:

```python
def _normalize_mapping(payload: dict) -> dict:
    normalized = {}
    for key in sorted(payload.keys()):        # Сортировка ключей для детерминированности
        value = _normalize_value(payload[key])
        if _is_empty(value):                  # Пропустить пустые
            continue
        normalized[str(key)] = value
    return normalized

def _is_empty(value) -> bool:
    return value is None or value == "" or (isinstance(value, (list, tuple, dict)) and not value)
```

**Пустые значения, которые удаляются:**
- `None`
- `""`  (пустая строка)
- `[]`  (пустой список)
- `{}`  (пустой словарь)

**Непустые значения, сохраняемые как есть:**
- `"emp_001"` → `"emp_001"`
- `0` (целочисленный ноль) → `0`  (не является пустым)
- `False` → `False`  (не является пустым)

### 3.3 `supported_versions()`

```python
def supported_versions(self) -> tuple[str, ...]:
    return ("v1",)
```

Возвращает список версий алгоритма локатора, поддерживаемых этим сервисом.
Используется при валидации и в будущем инструментарии миграции.

### 3.4 Требование согласованности записи/чтения

Locator hash вычисляется **идентично** как в пути записи
(`SecretVaultWriteService.put_many`), так и в пути чтения (`SecretVaultReadService.get_secret`).
Оба используют `source_ref = {"match_key": normalized_match_key}`, что обеспечивает одинаковый
канонический JSON независимо от исходной полноты входных данных.

---

## 4. `SecretVaultWriteService` — Путь записи

**Файл:** [`connector/domain/secrets/secret_vault_write_service.py`](../../../../connector/domain/secrets/secret_vault_write_service.py)

### 4.1 Конструктор

```python
SecretVaultWriteService(
    repository: SecretVaultRepositoryPort,
    cipher: SecretCipherPort,
    key_provider: VaultKeyProviderPort,
    locator: SecretLocatorPort,
    locator_version: str = "v1",
    cipher_algo: str = "FERNET_V1",
    wrap_algo: str = "FERNET_V1",
)
```

Все зависимости внедряются через порты — никакой прямой осведомлённости о SQLite, Fernet
или переменных окружения.

### 4.2 `put_many()` — Алгоритм записи

```
Вход: dataset="hr", match_key="emp_001", secrets={"password":"s3cr3t","pin":"1234"}, run_id=None

Шаг 0: Защита от пустого словаря secrets или пустого match_key.

Шаг 1: Начало транзакции vault (BEGIN IMMEDIATE).

Шаг 2: Получение активного DEK.
        active_master_key = key_provider.get_active_key()
        dek_record, dek_plaintext = _ensure_active_dek(active_master_key)

        _ensure_active_dek():
          а. repository.get_active_dek()
          б. если активный DEK существует:
               → _unwrap_dek(active_dek) → dek_plaintext (только в памяти)
          в. если DEK отсутствует:
               → dek_plaintext = base64.urlsafe_b64encode(os.urandom(32))
               → wrapped_dek = cipher.wrap_dek(dek_plaintext, master_key.key_material, wrap_algo)
               → repository.upsert_dek(VaultDekRecord(..., is_active=True))

Шаг 3: Для каждой пары (field, plaintext):
        source_ref = {"match_key": "emp_001"}  ← нормализовано из match_key
        locator_hash = locator.build_locator_hash(
            dataset="hr", field="password",
            source_ref=source_ref, locator_version="v1"
        )
        ciphertext = cipher.encrypt(
            plaintext="s3cr3t", dek_plaintext=dek_plaintext, cipher_algo="FERNET_V1"
        )
        repository.upsert_secret(VaultSecretRecord(
            dataset="hr", field="password",
            locator_hash=locator_hash, locator_version="v1",
            ciphertext=ciphertext, cipher_algo="FERNET_V1",
            key_version=active_master_key.key_version,
            dek_version=dek_record.dek_version,
            run_id=None, created_at=now, updated_at=now,
        ))

Шаг 4: Транзакция фиксируется (выход из контекстного менеджера).
```

### 4.3 Оборачивание ошибок в `put_many()`

```python
except SecretStoreError:
    raise                     # Передать как есть (уже доменная ошибка)
except SecretReadError as exc:
    raise SecretStoreError(..., details={"reason": "dek_read_failed"}) from exc
except (SecretKeyConfigError, SecretIntegrityError, SecretDecryptionError, ValueError) as exc:
    raise SecretStoreError(..., details={"reason": "crypto_error"}) from exc
except Exception as exc:
    raise SecretStoreError(..., details={"reason": "unexpected_error"}) from exc
```

Все ошибки, выходящие из `put_many()`, являются `SecretStoreError`. Исходное исключение
прикреплено как `__cause__` для полной доступности трассировки стека.

### 4.4 Выбор кандидатов мастер-ключей в `_unwrap_dek()`

```python
def _candidate_master_keys(self, wrap_key_version: str) -> list[VaultMasterKey]:
    candidates = []
    hinted = self._key_provider.find_key(wrap_key_version)  # O(1)
    if hinted is not None:
        candidates.append(hinted)        # Наиболее вероятный ключ первым (быстрый путь)
    for key in self._key_provider.get_all_keys():
        if hinted and key.key_version == hinted.key_version:
            continue                      # Дедупликация
        candidates.append(key)           # Полный keyring как запасной вариант
    return candidates
```

При получении `SecretDecryptionError` или `SecretIntegrityError` от любого кандидата
итерация продолжается к следующему. Если все кандидаты исчерпаны, выбрасывается `SecretStoreError`
с `reason="dek_unwrap_failed"`.

---

## 5. `SecretVaultReadService` — Путь чтения

**Файл:** [`connector/domain/secrets/secret_vault_read_service.py`](../../../../connector/domain/secrets/secret_vault_read_service.py)

### 5.1 Конструктор

```python
SecretVaultReadService(
    repository: SecretVaultRepositoryPort,
    cipher: SecretCipherPort,
    key_provider: VaultKeyProviderPort,
    locator: SecretLocatorPort,
    locator_version: str = "v1",
    default_run_id: str | None = None,
)
```

`default_run_id` — необязательное значение по умолчанию на уровне Factory — устанавливается,
когда контейнер создаёт сервис чтения для конкретного вызова с известным контекстом run_id.

### 5.2 `get_secret()` — Алгоритм чтения

```
Вход: dataset="hr", field="password", source_ref={"match_key":"emp_001"}, run_id="run_abc"

Шаг 0: _normalize_source_ref(source_ref)
        → Требует source_ref["match_key"] как непустую строку.
        → Возвращает {"match_key": "emp_001"} или None (прерывание: вернуть None).

Шаг 1: effective_run_id = run_id if run_id is not None else self._default_run_id

Шаг 2: locator_hash = locator.build_locator_hash(
            dataset="hr", field="password",
            source_ref={"match_key":"emp_001"}, locator_version="v1"
        )

Шаг 3: record = repository.get_secret(
            dataset="hr", field="password",
            locator_hash=locator_hash, locator_version="v1",
            run_id="run_abc",     ← двухуровневый приоритет (точное совпадение → NULL)
        )
        если record is None: вернуть None   (секрет не найден)

Шаг 4: dek_record = repository.get_dek(dek_version=record.dek_version)
        если dek_record is None:
            raise SecretReadError(reason="dek_not_found")

Шаг 5: dek_plaintext = _unwrap_dek(dek_record)
        (та же итерация по кандидатам ключей, что и в write-сервисе)

Шаг 6: plaintext = cipher.decrypt(
            ciphertext=record.ciphertext,
            dek_plaintext=dek_plaintext,
            cipher_algo=record.cipher_algo,
        )
        return plaintext   # "s3cr3t"
```

### 5.3 Семантика `None` против исключений

| Условие | Результат |
|---------|-----------|
| `source_ref` не содержит `match_key` | `None` (недостаточно контекста) |
| Секрет не найден в vault | `None` (не сохранён) |
| DEK отсутствует в vault_dek | `SecretReadError(reason="dek_not_found")` |
| Все ключи не смогли расшифровать DEK | `SecretDecryptionError(reason="dek_unwrap_failed")` |
| Зашифрованный текст повреждён | `SecretIntegrityError` |
| Ошибка хранилища | `SecretReadError` |

**Правило:** `None` означает «секрет не существует или контекст недостаточен».
Исключение означает «мы нашли следы секрета, но не можем его получить»
— это различие критично для конвейера apply, чтобы отличить
«никогда не сохранялся» от «ошибка хранилища».

### 5.4 `_normalize_source_ref()`

```python
def _normalize_source_ref(source_ref: dict | None) -> dict[str, str] | None:
    if not isinstance(source_ref, dict):
        return None
    raw_match_key = source_ref.get("match_key")
    if not isinstance(raw_match_key, str):
        return None
    normalized = raw_match_key.strip()
    if not normalized:
        return None
    return {"match_key": normalized}
```

Требуется только `match_key`. Прочие поля в `source_ref` молча отбрасываются
при нормализации пути чтения (согласованность с `source_ref = {"match_key": normalized}` пути записи).

---

## 6. `VaultStartupGuard` — Проверка при запуске

**Файл:** [`connector/domain/secrets/vault_startup_guard.py`](../../../../connector/domain/secrets/vault_startup_guard.py)

### 6.1 Назначение

`VaultStartupGuard` выполняет быструю проверку до того, как конвейер запустит
операции enrich или apply. Он гарантирует:

1. **Keyring корректен** — как минимум один ключ, совместимый с Fernet.
2. **Хранилище доступно для записи** — запись возможна согласно строгой политике v1.
3. **Целостность probe** — probe может быть зашифрован и расшифрован с текущим keyring.
4. **Доступность DEK** — как минимум один активный DEK может быть развёрнут.

### 6.2 Конструктор

```python
VaultStartupGuard(
    repository: SecretVaultRepositoryPort,
    cipher: SecretCipherPort,
    key_provider: VaultKeyProviderPort,
    storage_probe: _StorageReadinessProbe,    # SqliteEngine (утиная типизация)
    probe_name: str = "vault.system.healthcheck",
    probe_payload: str = "vault_startup_probe_v1",
    cipher_algo: str = "FERNET_V1",
    wrap_algo: str = "FERNET_V1",
    strict_readonly_policy: bool = True,
)
```

`storage_probe` — это `Protocol` с единственным методом `is_readonly() -> bool`.
`SqliteEngine` удовлетворяет этому протоколу через утиную типизацию — домен не
импортирует `SqliteEngine` напрямую.

### 6.3 `ensure_ready()` — Поток запуска

```
1. active_master_key = key_provider.get_active_key()
   → Падает в EnvVaultKeyProvider.__init__ при некорректном keyring (SecretKeyConfigError)
   → Этот вызов всегда успешен, если __init__ прошёл

2. readonly_storage = storage_probe.is_readonly()
   → SqliteEngine.is_readonly() выполняет тестовую запись; возвращает True если хранилище только для чтения

3. probe = _load_probe()                 → repository.get_probe("vault.system.healthcheck")

4а. probe is None И readonly_storage:
    → raise VaultStartupUninitializedReadonlyError
    (невозможно инициализировать probe на хранилище только для чтения)

4б. probe is None И NOT readonly_storage:
    → _create_probe(active_master_key)
    _create_probe():
      а. _ensure_active_dek(active_master_key)
         → get_active_dek() или генерация нового DEK + wrap + upsert_dek
      б. cipher.encrypt(probe_payload, dek_plaintext)
      в. repository.upsert_probe(VaultProbeRecord(...))
      г. _load_probe() снова для проверки записи (двойная проверка)

5. _validate_probe_record(probe):
   → Проверяет: probe_name совпадает, cipher_algo/key_version/dek_version непусты,
              ciphertext непуст
   → raise VaultStartupProbeCorruptedError при любой ошибке

6. _verify_probe(probe):
   → _load_probe_dek(probe) → repository.get_dek(probe.dek_version)
   → _unwrap_dek(dek_record) → перебор кандидатов ключей
   → cipher.decrypt(probe.ciphertext, dek_plaintext)
   → Если plaintext != "vault_startup_probe_v1" → VaultStartupProbeCorruptedError
   → Если расшифровка не удалась → VaultStartupKeyValidationError (неверный ключ)
   → Если ошибка целостности → VaultStartupProbeCorruptedError (повреждённое хранилище)

7. readonly_storage И strict_readonly_policy:
   → raise VaultStartupStorageReadonlyError
   (доступно для чтения, но не для записи → строгая политика v1 блокирует запуск)
```

### 6.4 Таксономия ошибок запуска

| Ошибка | Код | Условие |
|--------|-----|---------|
| `VaultStartupKeyValidationError` | `VAULT_STARTUP_KEY_VALIDATION_ERROR` | Расшифровка probe не удалась — keyring несовместим |
| `VaultStartupProbeCorruptedError` | `VAULT_STARTUP_PROBE_CORRUPTED` | Структура probe некорректна, запись не удалась, данные не совпадают |
| `VaultStartupStorageReadonlyError` | `VAULT_STARTUP_STORAGE_READONLY` | Хранилище только для чтения, активна строгая политика |
| `VaultStartupUninitializedReadonlyError` | `VAULT_STARTUP_UNINITIALIZED_READONLY` | Probe отсутствует, и хранилище только для чтения |
| `SecretKeyConfigError` | `VAULT_STARTUP_KEY_CONFIG_ERROR` | Некорректный keyring при `EnvVaultKeyProvider.__init__` |

### 6.5 Строгая политика только для чтения (v1)

```
strict_readonly_policy = True  (по умолчанию)

probe существует + доступно для записи: OK, продолжить нормально
probe существует + только для чтения:   ЗАБЛОКИРОВАНО → VaultStartupStorageReadonlyError
                                         Причина: запись в vault во время enrich будет падать
probe отсутствует + доступно для записи: авто-инициализация probe, затем OK
probe отсутствует + только для чтения:  ЗАБЛОКИРОВАНО → VaultStartupUninitializedReadonlyError
                                         Причина: невозможно даже инициализировать
```

Эта политика гарантирует, что конвейер никогда не переходит к этапам enrich/apply,
где записи секретов будут падать с непонятными ошибками в середине выполнения.

### 6.6 Протокол `_StorageReadinessProbe`

```python
class _StorageReadinessProbe(Protocol):
    def is_readonly(self) -> bool: ...
```

`SqliteEngine.is_readonly()` — производственная реализация. Она выполняет
лёгкую тестовую запись (например, пытается открыть транзакцию записи) и
возвращает `True`, если файл базы данных находится в файловой системе только для чтения
или заблокирован другим процессом в монопольном режиме.

---

## 7. `VaultRetentionService` — Жизненный цикл после apply

**Файл:** [`connector/domain/secrets/vault_retention_service.py`](../../../../connector/domain/secrets/vault_retention_service.py)

### 7.1 Назначение

Вызывается после каждого **успешного** вызова целевого API во время этапа apply. Его роль —
очистка ephemeral-секретов, которые больше не нужны после передачи секрета в целевую систему.

### 7.2 Конструктор

```python
VaultRetentionService(
    repository: SecretVaultRepositoryPort,
    locator: SecretLocatorPort,
    locator_version: str = "v1",
)
```

Без шифра и провайдера ключей — сервис retention только удаляет строки, никогда не читает открытый текст.

### 7.3 `on_apply_success()` — Логика удаления при успехе

```
Вход:
  dataset="hr", op="create_user",
  source_ref={"match_key":"emp_001"},
  secret_fields=["password","pin"],
  secret_lifecycle={"mode":"ephemeral"},
  run_id=None

Шаг 1: normalize_secret_lifecycle(secret_lifecycle)
        → policy = {"mode": "ephemeral", "delete_on_success": True, "ttl_seconds": None}

Шаг 2: если policy["mode"] != "ephemeral" ИЛИ NOT policy["delete_on_success"]:
          counters["kept"] += len(secret_fields)
          return counters   ← persistent-режим: очистка не нужна

Шаг 3: match_key = _extract_match_key(source_ref)
        если match_key is None:
          counters["skipped"] += len(secret_fields)
          return counters   ← невозможно построить locator без match_key

Шаг 4: для каждого field в secret_fields:
          try:
            locator_hash = locator.build_locator_hash(
                dataset="hr", field=field,
                source_ref={"match_key":"emp_001"}, locator_version="v1"
            )
            deleted = repository.delete_secret(
                dataset="hr", field=field,
                locator_hash=locator_hash, locator_version="v1",
                run_id=None,
            )
            если deleted > 0: counters["deleted"] += deleted
            иначе:            counters["skipped"] += 1
          except (SecretStoreError, ValueError):
            counters["errors"] += 1    ← по возможности: никогда не бросает исключение наружу

return counters  # {"deleted": 2, "kept": 0, "skipped": 0, "errors": 0}
```

### 7.4 Режимы жизненного цикла

| `mode` | `delete_on_success` | Поведение |
|--------|---------------------|-----------|
| `persistent` (по умолчанию) | `False` | Секрет остаётся в vault после apply |
| `ephemeral` | `True` (неявно) | Секрет удаляется после успешного apply |
| `ephemeral` | `False` (явное переопределение) | Режим ephemeral, но удаление подавлено |
| Любой | явный `True` | Удалить независимо от режима |

### 7.5 `run_maintenance()` — Хуки

```python
def run_maintenance(self) -> Mapping[str, int]:
    return {
        "cleanup_expired": self.cleanup_expired(),   # v1: 0 (заглушка)
        "cleanup_orphans": self.cleanup_orphans(),   # v1: 0 (заглушка)
        "rewrap_candidates": self.rewrap_candidates(), # v1: 0 (заглушка)
    }
```

Все три операции обслуживания — заглушки v1. Они возвращают 0 и ничего не логируют.
В будущих версиях будет реализовано:
- `cleanup_expired()`: удаление секретов, превысивших `ttl_seconds`.
- `cleanup_orphans()`: удаление секретов без соответствующего vault_dek.
- `rewrap_candidates()`: повторная обёртка DEK новым активным мастер-ключом.

---

## 8. Модули политик

### 8.1 `retention_policy.py` — `normalize_secret_lifecycle()`

**Файл:** [`connector/domain/secrets/policy/retention_policy.py`](../../../../connector/domain/secrets/policy/retention_policy.py)

```python
def normalize_secret_lifecycle(raw: dict | None) -> dict:
    """
    Returns: {"mode": str, "delete_on_success": bool, "ttl_seconds": int | None}
    """
```

**Правила валидации:**

| Поле | Допустимые значения | По умолчанию |
|------|---------------------|--------------|
| `mode` | `"persistent"`, `"ephemeral"` | `"persistent"` |
| `delete_on_success` | `bool` (явное) или производное от mode | `False` для persistent, `True` для ephemeral |
| `ttl_seconds` | положительный `int` | `None` |

**Таблица решений:**

```
raw = None                 → {"mode":"persistent", "delete_on_success": False, "ttl_seconds": None}
raw = {"mode":"ephemeral"} → {"mode":"ephemeral",  "delete_on_success": True,  "ttl_seconds": None}
raw = {"mode":"ephemeral", "delete_on_success": False} → явное переопределение: delete_on_success=False
raw = {"mode":"persistent","ttl_seconds":3600}         → {"mode":"persistent","delete_on_success":False,"ttl_seconds":3600}
raw = {"mode":"invalid"}   → mode по умолчанию "persistent"
raw = {"ttl_seconds":"600"}→ ttl_seconds=None (принимается только int)
```

### 8.2 `runtime_mode_policy.py` — `resolve_vault_runtime_mode()`

**Файл:** [`connector/domain/secrets/policy/runtime_mode_policy.py`](../../../../connector/domain/secrets/policy/runtime_mode_policy.py)

```python
def resolve_vault_runtime_mode(
    *, mode: str | None, requires_vault: bool
) -> VaultRuntimeModeDecision:
```

**Назначение:** Определить, следует ли активировать vault для данного
запуска конвейера, на основе указанного пользователем режима и наличия секретных полей в датасете.

**Режимы:**

| `mode` | `requires_vault` | `requested_vault` | `reason` |
|--------|-----------------|-------------------|----------|
| `"on"` | любое | `True` | `"runtime_mode_on"` |
| `"off"` | любое | `False` | `"runtime_mode_off"` |
| `"auto"` | `True` | `True` | `"runtime_auto_secret_fields_detected"` |
| `"auto"` | `False` | `False` | `"runtime_auto_secret_fields_absent"` |
| `None` | любое | То же, что `"auto"` | (None нормализуется до auto) |
| некорректный | любое | `False` | `"runtime_mode_invalid"` |

**Поля `VaultRuntimeModeDecision`:**

```python
@dataclass(frozen=True)
class VaultRuntimeModeDecision:
    mode: str           # Нормализованный: "auto" | "on" | "off"
    requested_vault: bool   # Вход для политики rollout
    requires_vault: bool    # Есть ли в датасете секретные поля
    explicit_mode: bool     # True если mode задан явно (не None)
    reason: str             # Строка для наблюдаемости
```

Выходное значение `requested_vault` является ключевым и передаётся в `evaluate_vault_rollout()`
как параметр `requested_vault`.

### 8.3 `rollout_policy.py` — `evaluate_vault_rollout()`

**Файл:** [`connector/domain/secrets/policy/rollout_policy.py`](../../../../connector/domain/secrets/policy/rollout_policy.py)

```python
def evaluate_vault_rollout(
    *, settings: VaultRolloutPolicySettings,
    requested_vault: bool, dataset: str | None,
    run_id: str | None, command_name: str,
) -> VaultRolloutDecision:
```

**Назначение:** Управление активацией vault при поэтапном производственном rollout. Определяет,
будет ли vault работать для конкретной комбинации dataset/run_id.

#### Режимы rollout

| Режим | Поведение | `vault_enabled` | `startup_guard_required` | `force_dry_run` |
|-------|-----------|-----------------|--------------------------|-----------------|
| `"off"` | Vault никогда не запускается | `False` | `False` | `False` |
| `"full"` | Vault всегда запускается | `True` | `True` | `False` |
| `"staging_dry_run"` | Vault запускается, но записи apply — dry-run | `True` | `True` | `True` (для import-apply) |
| `"canary"` | Vault запускается для выбранного процента по hash | `True` или `False` | Если выбран | `False` |

#### Алгоритм canary

```python
def compute_canary_bucket(*, seed: str, dataset: str | None, run_id: str | None) -> int:
    raw = f"{seed}|{dataset or '<none>'}|{run_id or '<none>'}"
    digest = sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100     # Бакет: 0..99
```

```
canary_percent = 20
bucket = compute_canary_bucket(seed="vault-rollout-v1", dataset="hr", run_id="run_abc")
selected = bucket < 20    # True если bucket в [0, 19]
```

Hash детерминирован для `(seed, dataset, run_id)` — один и тот же запуск всегда
попадает в один и тот же бакет. Это значит, что canary стабилен при повторных попытках.

#### Список разрешённых датасетов

```python
def _is_dataset_allowed(dataset: str | None, allowlist: tuple[str, ...]) -> bool:
    if not allowlist: return True       # Пустой список = все датасеты разрешены
    if "*" in allowlist: return True    # Wildcard
    if not dataset: return False        # Датасет не указан, отфильтрован
    return dataset in allowlist
```

#### Поля `VaultRolloutDecision`

```python
@dataclass(frozen=True)
class VaultRolloutDecision:
    requested_vault: bool      # Был ли запрошен vault политикой runtime?
    mode: str                  # Нормализованный режим rollout
    vault_enabled: bool        # Должен ли vault работать для этого вызова?
    startup_guard_required: bool  # Должен ли выполняться VaultStartupGuard.ensure_ready()?
    force_dry_run: bool        # Подавить реальные записи на этапе apply?
    canary_bucket: int | None  # Бакет [0..99] для canary; None для не-canary режимов
    canary_selected: bool | None  # Был ли этот запуск выбран canary
    reason: str                # Строка для наблюдаемости
```

#### Коды причин

| `reason` | Условие |
|---------|---------|
| `"vault_not_requested"` | `requested_vault=False` из политики runtime |
| `"rollout_mode_off"` | Режим `"off"` |
| `"rollout_full_enabled"` | Режим `"full"` |
| `"rollout_staging_dry_run"` | Режим `"staging_dry_run"` |
| `"rollout_canary_selected"` | Canary: бакет выбран |
| `"rollout_canary_bucket_filtered"` | Canary: бакет не выбран |
| `"rollout_canary_dataset_filtered"` | Canary: датасет не в списке разрешённых |
| `"rollout_canary_percent_zero"` | Canary: `canary_percent <= 0` |

### 8.4 `rollout_metrics.py` — `build_vault_operational_metrics()`

**Файл:** [`connector/domain/secrets/policy/rollout_metrics.py`](../../../../connector/domain/secrets/policy/rollout_metrics.py)

Вычисляет операционные метрики для принятия решений об откате во время canary rollout.
Возвращает сериализуемый словарь для включения в контекст отчёта apply.

**Ключевые вычисляемые метрики:**
- `startup_success_rate_pct` — доля успешных запусков vault
- `secret_read_success_rate_pct` — доля успешных операций чтения секретов
- `vault_error_rate_pct` — доля ошибок, связанных с vault, при обработке apply
- `row_failure_rate_pct` — доля строк apply, завершившихся ошибкой
- Условия активации отката: `startup_error`, высокий `row_failure_rate`, высокий `vault_error_rate`

---

## 9. Двухфазная оценка политики

Оценка политики vault — это двухфазный барьер:

```
Фаза 1: resolve_vault_runtime_mode(mode, requires_vault) → VaultRuntimeModeDecision
             ↓ .requested_vault
Фаза 2: evaluate_vault_rollout(settings, requested_vault, dataset, run_id) → VaultRolloutDecision
             ↓ .vault_enabled
Фаза 3: если vault_enabled: startup_guard.ensure_ready() (если .startup_guard_required)
         если vault_enabled: использовать write_service / read_service
```

**Фаза 1** отвечает на вопрос: «Нужен ли vault этому запуску конвейера вообще?»
**Фаза 2** отвечает на вопрос: «Если vault нужен, разрешает ли политика rollout его для данного конкретного запуска?»

---

## 10. `VaultContainer` — DI-подключение

**Файл:** [`connector/delivery/cli/containers.py:245`](../../../../connector/delivery/cli/containers.py#L245)

```python
class VaultContainer(containers.DeclarativeContainer):
    vault_engine = providers.Dependency(instance_of=SqliteEngine)

    cipher     = providers.Singleton(FernetEnvelopeCipher)
    key_provider = providers.Singleton(EnvVaultKeyProvider)
    locator    = providers.Singleton(SecretLocatorService)
    repository = providers.Singleton(SqliteVaultRepository, engine=vault_engine)

    read_service = providers.Factory(
        SecretVaultReadService,
        repository=repository, cipher=cipher,
        key_provider=key_provider, locator=locator,
    )

    write_service = providers.Factory(
        SecretVaultWriteService,
        repository=repository, cipher=cipher,
        key_provider=key_provider, locator=locator,
    )

    retention_service = providers.Factory(
        VaultRetentionService,
        repository=repository, locator=locator,
    )
```

### 10.1 Различие Singleton и Factory

| Провайдер | Тип | Причина |
|-----------|-----|---------|
| `cipher` | Singleton | Без состояния; объект Fernet переиспользуем |
| `key_provider` | Singleton | Keyring разбирается один раз при запуске, неизменяем |
| `locator` | Singleton | Без состояния; выполняет только sha256 |
| `repository` | Singleton | Единственный пул соединений на весь срок жизни движка |
| `read_service` | Factory | Может нести `default_run_id` конкретного вызова |
| `write_service` | Factory | Возможно состояние на вызов (в данный момент отсутствует) |
| `retention_service` | Factory | Состояние на вызов (счётчики в вызывающей стороне) |

### 10.2 Зависимость `vault_engine`

`vault_engine` — это `Dependency` — сам `VaultContainer` не создаёт его.
Он внедряется через `AppContainer` из `SqliteContainer.vault_engine`:

```python
class AppContainer:
    sqlite = providers.Container(SqliteContainer, ...)
    vault = providers.Container(VaultContainer, vault_engine=sqlite.vault_engine)
```

Это означает, что `VaultContainer` никогда не открывает и не закрывает соединение с базой данных —
этот жизненный цикл полностью управляется `SqliteContainer`.

---

## 11. `vault_startup_resource()` — Ресурс жизненного цикла

**Файл:** [`connector/delivery/cli/containers.py:140`](../../../../connector/delivery/cli/containers.py#L140)

```python
def vault_startup_resource(engine: SqliteEngine) -> Iterator[None]:
    ensure_vault_schema(engine)
    guard = VaultStartupGuard(
        repository=SqliteVaultRepository(engine),
        cipher=FernetEnvelopeCipher(),
        key_provider=EnvVaultKeyProvider(),
        storage_probe=engine,
    )
    guard.ensure_ready()
    yield
    engine.close()
```

Это `providers.Resource` в `SqliteContainer.vault_ready`.

**Жизненный цикл:**
1. `ensure_vault_schema(engine)` — создаёт или мигрирует схему vault.
2. `VaultStartupGuard(...)` — конструирует guard со свежими экземплярами.
3. `guard.ensure_ready()` — выполняет полную проверку при запуске (может выбрасывать `VAULT_STARTUP_*`).
4. `yield` — ресурс активен; контейнер держит движок открытым.
5. `engine.close()` — завершение при отключении контейнера.

**Примечание:** `VaultStartupGuard`, создаваемый здесь, использует свежие экземпляры
`FernetEnvelopeCipher()` и `EnvVaultKeyProvider()` — не Singleton-ы из
`VaultContainer`. Это сделано намеренно: startup guard запускается до
подключения `VaultContainer` и использует ту же реализацию переменных окружения / Fernet
независимо.

### Когда инициализируется `vault_ready`?

```python
def _init_container_for_requirements(container, req):
    if req.requires_vault_init:
        container.sqlite.vault_ready.init()
```

Ресурс `vault_ready` лениво инициализируется через `_init_container_for_requirements()`
на основе объекта `Requirements` выполняемой команды. Только команды, объявляющие
`requires_vault_init=True`, запускают инициализацию vault.

---

## 12. `SqliteContainer` — Управление движком

**Файл:** [`connector/delivery/cli/containers.py:186`](../../../../connector/delivery/cli/containers.py#L186)

```python
class SqliteContainer(containers.DeclarativeContainer):
    app_config = providers.Dependency(instance_of=AppConfig)
    cache_dir  = providers.Dependency(instance_of=str)
    cache_specs = providers.Dependency(instance_of=list)

    vault_engine = providers.Singleton(_make_vault_engine, app_config=app_config, cache_dir=cache_dir)
    vault_ready  = providers.Resource(vault_startup_resource, engine=vault_engine)
```

`_make_vault_engine()` открывает `SqliteEngine` к файлу базы данных vault:

```python
def _make_vault_engine(app_config: AppConfig, cache_dir: str) -> SqliteEngine:
    return open_sqlite(to_vault_db_config(app_config), _vault_db_path(cache_dir, app_config.sqlite))
```

Путь к движку определяется из `cache_dir` + настроек `app_config.sqlite`.

---

## 13. Взаимодействие слоёв

```
Слой политик (чистые функции, без I/O):
  resolve_vault_runtime_mode()   →  VaultRuntimeModeDecision.requested_vault
  evaluate_vault_rollout()       →  VaultRolloutDecision.vault_enabled
         │
         ▼ (условно на vault_enabled)
Слой доменных сервисов:
  VaultStartupGuard.ensure_ready()   →  проверка при запуске
  SecretVaultWriteService.put_many()  →  шифрование + сохранение
  SecretVaultReadService.get_secret() →  загрузка + расшифровка
  VaultRetentionService.on_apply_success() → удаление (режим ephemeral)
         │ использует только порты
         ▼
  SecretLocatorPort  ←  SecretLocatorService
  SecretCipherPort   ←  FernetEnvelopeCipher
  VaultKeyProviderPort ← EnvVaultKeyProvider
  SecretVaultRepositoryPort ← SqliteVaultRepository
         │
         ▼
  SQLite vault_secrets, vault_dek, vault_probe (хранилище)
```

---

## 14. Типичные сценарии

### Сценарий A: Первый запуск конвейера с включённым vault

```
1. _init_container_for_requirements() → requires_vault_init → vault_ready.init()
2. vault_startup_resource():
   а. ensure_vault_schema() → создаёт таблицы
   б. VaultStartupGuard.ensure_ready()
      → probe отсутствует → хранилище доступно для записи → создаём probe
      → генерируем DEK → оборачиваем активным мастер-ключом → upsert_dek
      → шифруем данные probe → upsert_probe
      → проверяем probe: расшифровываем → данные совпадают
      → хранилище доступно для записи: нет StorageReadonlyError
3. Конвейер запускается. Этап enrich:
   write_service.put_many("hr", "emp_001", {"password":"s3cr3t"})
4. Этап apply:
   read_service.get_secret("hr", "password", source_ref={"match_key":"emp_001"})
   → "s3cr3t"
5. При успешном apply:
   retention_service.on_apply_success(secret_fields=["password"],
       secret_lifecycle={"mode":"ephemeral"})
   → delete_secret("hr","password",locator_hash=sha256(...))
```

### Сценарий B: Canary rollout (20%)

```
settings = VaultRolloutPolicySettings(mode="canary", canary_percent=20)
runtime_decision = resolve_vault_runtime_mode(mode="auto", requires_vault=True)
# → requested_vault=True

rollout_decision = evaluate_vault_rollout(
    settings=settings, requested_vault=True,
    dataset="hr", run_id="run_001", command_name="import-enrich"
)
# bucket = sha256("vault-rollout-v1|hr|run_001")[:8] % 100 = например 7
# selected = 7 < 20  → True

if rollout_decision.vault_enabled:
    guard.ensure_ready()
    # продолжить с записью/чтением vault
```

### Сценарий C: Ротация ключей в процессе работы

```
До:   ANKEY_VAULT_MASTER_KEYS=v1:<old_key>
После: ANKEY_VAULT_MASTER_KEYS=v2:<new_key>,v1:<old_key>

1. EnvVaultKeyProvider читает новые переменные окружения:
   active_key = v2, keyring = [v2, v1]

2. Новые секреты: зашифрованы с DEK, обёрнутым ключом v2.
3. Старые секреты: DEK по-прежнему обёрнут ключом v1.

4. read_service.get_secret() для старого секрета:
   → record.key_version = "v1"
   → _candidate_master_keys("v1") = [v1_key, v2_key]
   → Попытка с v1 → разворачиваем DEK → успех
   → расшифровываем ciphertext → возвращаем открытый текст

5. После ручной повторной обёртки всех старых DEK (rewrap_candidates в будущем):
   → Удалить v1 из переменных окружения → ANKEY_VAULT_MASTER_KEYS=v2:<new_key>
```

### Сценарий D: Запуск на файловой системе только для чтения

```
1. vault_startup_resource() вызывается.
2. ensure_vault_schema() → падает если схема не существует → SecretStoreError
   (или завершается успешно если схема была создана заранее)
3. guard.ensure_ready():
   а. storage_probe.is_readonly() → True
   б. _load_probe() → probe найден (создан заранее)
   в. _validate_probe_record(probe) → OK
   г. _verify_probe(probe) → расшифровка → OK
   д. strict_readonly_policy=True → raise VaultStartupStorageReadonlyError
4. Запуск конвейера заблокирован.
```

---

## 15. Важные детали реализации

### 15.1 Соглашение о `source_ref`

Оба пути — записи и чтения — нормализуют `source_ref` до `{"match_key": <normalized_key>}`.
Locator hash строится из этой нормализованной формы. Прочие поля исходного
`source_ref` отбрасываются для нужд vault, тогда как полный `source_ref` может
использоваться другими подсистемами (например, при построении контекста plan-mode).

### 15.2 Factory-сервисы против Singleton-репозитория

`write_service`, `read_service` и `retention_service` — это `providers.Factory`
— новый экземпляр создаётся при каждом вызове `container.vault.write_service()`.
Они не хранят внутреннего состояния, сохраняющегося между вызовами. Репозиторий и шифр
являются Singleton-ами, передаваемыми как зависимости.

### 15.3 `default_run_id` в ReadService

При создании `read_service` через Factory вызывающие стороны могут передать `default_run_id`:

```python
svc = container.vault.read_service(default_run_id="run_abc")
secret = svc.get_secret(dataset="hr", field="pw", source_ref={"match_key":"emp"})
# effective_run_id = "run_abc" (использует значение по умолчанию, поскольку get_secret вызван с run_id=None)
```

Это позволяет конвейеру apply устанавливать run_id один раз при создании Factory,
а не передавать его в каждый вызов `get_secret()`.

### 15.4 Отсутствие vault в отключённом режиме

Когда `vault_enabled=False` (решение rollout):
- `guard.ensure_ready()` не вызывается.
- `write_service` и `read_service` не используются.
- Секреты не сохраняются и не извлекаются.
- Конвейер работает так, как если бы vault не существует.

Этот путь не требует никаких изменений в доменных сервисах — это чисто
маршрутизационное решение delivery-слоя.

### 15.5 Распространение ошибок из политик

Функции политик являются чистыми (без I/O, без исключений при нормальной работе):
- `normalize_secret_lifecycle()` — всегда возвращает словарь; некорректные входные данные приводятся к значениям по умолчанию.
- `resolve_vault_runtime_mode()` — всегда возвращает `VaultRuntimeModeDecision`; неизвестный режим → `requested_vault=False`.
- `evaluate_vault_rollout()` — всегда возвращает `VaultRolloutDecision`; неизвестный режим → трактуется как `"off"`.

Это означает, что оценка политики никогда не выбрасывает исключений — верхние слои всегда получают
объект решения и могут выполнять ветвление по `.vault_enabled`.

---

## 16. Контракты и границы

| Граница | Вход | Выход | Ошибки |
|---------|------|-------|--------|
| `write_service.put_many()` | `(dataset, match_key, secrets, run_id)` | None (побочный эффект: сохранено) | `SecretStoreError` |
| `read_service.get_secret()` | `(dataset, field, source_ref, run_id)` | `str` или `None` | `SecretReadError`, `SecretDecryptionError`, `SecretIntegrityError` |
| `locator.build_locator_hash()` | `(dataset, field, source_ref, version)` | `str` sha256 hex | `ValueError` для неподдерживаемой версии |
| `startup_guard.ensure_ready()` | — | None (побочный эффект: probe создан/проверен) | Ошибки `VAULT_STARTUP_*` |
| `retention_service.on_apply_success()` | `(dataset, op, source_ref, secret_fields, lifecycle, run_id)` | `Mapping[str, int]` счётчики | Никогда не выбрасывает (по возможности) |
| `resolve_vault_runtime_mode()` | `(mode, requires_vault)` | `VaultRuntimeModeDecision` | Никогда не выбрасывает |
| `evaluate_vault_rollout()` | `(settings, requested_vault, dataset, run_id)` | `VaultRolloutDecision` | Никогда не выбрасывает |
| `normalize_secret_lifecycle()` | `dict | None` | `{"mode","delete_on_success","ttl_seconds"}` | Никогда не выбрасывает |

---

## 17. Vault-Management Delivery Контур (DEC-002)

### 17.1 Где находится orchestration

| Слой | Модуль | Ответственность |
|------|--------|-----------------|
| Delivery | `connector/delivery/cli/app.py` | CLI namespace `syncEmployees vault-management <subcommand>` и парсинг флагов |
| Delivery | `connector/delivery/commands/vault_management.py` | Confirm/password gate, dry-run payload, вызов usecase |
| Usecase | `connector/usecases/management/vault/usecase.py` | Lifecycle orchestration `init/status/rotate/rewrap/delete-key` |
| Usecase | `connector/usecases/management/vault/maintenance.py` | `run_if_due`, bridge recovery и due-gate |
| Infra | `connector/infra/secrets/management/managed_env_keyring_store.py` | Managed keyring file IO (atomic write + lock + permissions) |
| Infra | `connector/infra/secrets/management/admin_password_gate.py` | Manual access gate (argon2id verify) |
| Domain | `connector/domain/secrets/policy/rotation_policy.py` | Чистая due-политика без IO |

Граница ответственности:
- Delivery слой не содержит rotate/rewrap алгоритм.
- Usecase слой не содержит CLI/prompt parsing.
- Domain policy не знает о файлах, ENV и DI.

### 17.2 Startup integration

`vault_startup_resource()` выполняет:
1. `ensure_vault_schema(engine)`.
2. Preload effective keyring с precedence `runtime ENV -> managed env file`.
3. Optional maintenance (`auto_rotate_enabled=true`) с политикой ошибок:
   - `fail_closed`: исключение прерывает startup.
   - `fail_open`: ошибка maintenance не блокирует startup.
4. Финальный `VaultStartupGuard.ensure_ready()`.

### 17.3 Реальный CLI контракт

Subcommands:
- `init`
- `status`
- `rotate`
- `rewrap`
- `delete-key`
- `run-maintenance`

Общие флаги:
- `--force`
- `--dry-run`
- `--non-interactive`
- `--verify/--no-verify`
- `--managed-env-file`

Специальный флаг:
- `init --import-existing-env`

Поведение confirm/gate:
- при `--non-interactive` обязателен `--force`;
- manual operations (`init/rotate/rewrap/delete-key/run-maintenance`) проходят через `VaultAdminPasswordGate`;
- `status` является read-only и gate не требует.

### 17.4 Контракт `delete-key`

`delete-key` реализован только как replace-flow:
1. Генерируется новый active key.
2. Выполняется rewrap всех DEK.
3. Выполняется post-verify.
4. Steady-state возвращается к single-key (`new` only).

Прямого удаления единственного active key нет.

---

## 18. Связанные документы

- [vault-core.md](vault-core.md) — Как write/read-сервисы встраиваются в конвейер:
  `SecretStoreProtocol` в enrich, `SecretProviderProtocol` в apply
- [vault-crypto.md](vault-crypto.md) — Что делают `FernetEnvelopeCipher` и `EnvVaultKeyProvider`
  внутри сервисов
- [vault-storage.md](vault-storage.md) — Что происходит внутри вызовов `repository.*`:
  SQL-запросы, область видимости run_id, маппинг ошибок

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Vault Delivery | xORex-LC |
| 2026-03-07 | Добавлен раздел DEC-002: delivery-контур `vault-management`, startup integration и CLI контракт | xORex-LC |
