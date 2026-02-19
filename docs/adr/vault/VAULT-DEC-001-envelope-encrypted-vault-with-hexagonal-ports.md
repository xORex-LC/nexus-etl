# VAULT-DEC-001: Envelope-encrypted vault с hexagonal разделением crypto/storage

> **Статус**: Принято
> **Дата принятия**: 2026-02-18
> **Решает проблему**: [VAULT-PROBLEM-001](./VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md)
> **Участники решения**: @adminkii, @xorex

---

## 📋 Контекст

Текущий секретный контур (enrich -> plan -> apply) по процессу корректен, но production-требования не выполняются:
- dev-vault хранит секреты в plaintext CSV;
- отсутствует изоляция криптографии от хранения;
- не определён lifecycle ключей и стратегия ротации;
- не стандартизованы доменные ошибки дешифрования/целостности.

Нужно получить production-ready подсистему, сохранив чистое разделение ответственности и возможность замены backend хранилища.

---

## 🎯 Решение

Принято решение реализовать Vault-подсистему по принципу hexagonal architecture:

1. **Сохранить текущие application-level порты** (`SecretProviderProtocol`, `SecretStoreProtocol`) как внешние точки интеграции pipeline/apply.
2. **Внутри Vault-подсистемы** выделить отдельные порты:
   - storage-порт (репозиторий vault-записей),
   - crypto-порт (encrypt/decrypt),
   - key-provider (получение мастер-ключей из ENV).
3. Реализовать **envelope encryption**:
   - мастер-ключи задаются пользователем в ENV;
   - DEK генерируется системой;
   - DEK хранится в БД в зашифрованном виде (wrapped мастер-ключом);
   - секретные значения шифруются DEK.
4. Первый production backend — **SQLite vault в отдельном DB-файле** (по умолчанию `cache/ankey_vault.sqlite3`), но доступ к нему идёт только через `SecretVaultRepositoryPort` (не через cache role-порты).
5. Политика apply: если поле не указано в `secret_fields` для операции, **поле не отправляется в payload**.
6. Runtime-путь `FileVault*` (plaintext CSV) выводится из прод-контура; допускается только одноразовая миграция legacy данных.
7. Добавить `VaultStartupGuard` (fail-fast): в bootstrap до запуска use-case проверять валидность ключей и способность расшифровать/прочитать служебную probe-запись vault.
8. Зафиксировать единый locator-контракт (`dataset + field + canonical source_ref -> locator_hash`) как часть доменной логики, чтобы enrich/apply использовали идентичный ключ адресации.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `SecretCipherPort` (domain port) — шифрование/дешифрование.
- `SecretVaultRepositoryPort` (domain port) — чтение/запись ciphertext и metadata.
- `VaultKeyProviderPort` (domain port) — загрузка активного и предыдущих master keys.
- `SecretLocatorService` (domain service) — канонизация `source_ref` и построение `locator_hash`.
- `SecretVaultWriteService` — запись секретов (locator -> encrypt -> persist).
- `SecretVaultReadService` — чтение секретов (load -> decrypt -> return plaintext).
- `VaultStartupGuard` — startup-проверка key/vault readiness через служебную probe-запись.
- `FernetEnvelopeCipher` (infra) — реализация crypto-порта.
- `VaultSqliteDb` (infra) — path/open policy для отдельного vault DB-файла.
- `SqliteVaultRepository` (infra) — реализация storage-порта.
- `VaultSqliteSchema` (infra) — vault-only schema/migrations lifecycle.
- `EnvVaultKeyProvider` (infra) — реализация key-provider порта.

**Изменения в существующих компонентах**:
- `EnricherCore` продолжает писать через `SecretStoreProtocol`, но фактическая реализация переводится на `SecretVaultWriteService`.
- `OperationApplyAdapter` продолжает читать через `SecretProviderProtocol`, но реализация переводится на `SecretVaultReadService`.
- `build_secret_provider()` в режиме `vault` становится vault-only (без prompt fallback).
- `bootstrap` добавляет `VaultStartupGuard.ensure_ready()` до запуска `import plan/apply/enrich`.

### Интерфейсы

```python
class SecretCipherPort(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...

class SecretVaultRepositoryPort(Protocol):
    def put_secret(self, *, dataset: str, field: str, locator_hash: str, ciphertext: str, key_version: str, run_id: str | None) -> None: ...
    def get_secret(self, *, dataset: str, field: str, locator_hash: str, run_id: str | None) -> dict | None: ...

class VaultKeyProviderPort(Protocol):
    def active_master_key(self) -> str: ...
    def all_master_keys(self) -> tuple[str, ...]: ...

class SecretLocatorPort(Protocol):
    def build_locator_hash(self, *, dataset: str, field: str, source_ref: dict[str, object] | None) -> str: ...
```

### Граница с cache слоем

- Vault не использует cache role-порты (`EnrichLookupPort`, `PlanningRuntimePort`, `ApplyRuntimePort`) для операций чтения/записи секретов.
- Vault использует отдельное SQLite-подключение и отдельный DB-файл.
- Разрешено переиспользовать только infra-механику подключения к SQLite (connection/transaction lifecycle), но не общий cache gateway.
- Миграции vault поддерживаются отдельно от cache schema version (отдельный `vault_meta` и `vault` schema lifecycle).
- Любая смена backend (SQLite -> Postgres/KMS-backed store) не должна затрагивать domain/usecase контракты секретов.

### SQLite storage profile (принято)

- Vault хранится в отдельном DB-файле (`cache/ankey_vault.sqlite3` по умолчанию, override через `ANKEY_VAULT_DB_PATH`).
- Отдельная БД-схема/namespace в SQLite не используется (ограничение SQLite); под «отдельной схемой» здесь понимается отдельный файл схемы/миграций (`connector/infra/secrets/sqlite/schema.py`), а изоляция данных делается через `vault_*` таблицы.
- Repository и schema-модуль размещаются в `connector/infra/secrets/sqlite/`, не в `connector/infra/cache/repository/`.
- Отдельный индекс по surrogate `id` не добавляется при `PRIMARY KEY`; индексация строится по lookup-контракту (`dataset`, `field`, `locator_version`, `locator_hash`, `run_id`).
- `updated_at` ведётся приложением, `created_at` может иметь DB fallback (`CURRENT_TIMESTAMP`).
- Для crypto-agility в storage добавляются поля алгоритмов:
  - `vault_secrets.cipher_algo` (например, `FERNET_V1`);
  - `vault_dek.wrap_algo` (например, `FERNET_V1`).

### Модель секрета

Секрет в домене разделяется на два слоя:

1. **Непрозрачное тело секрета (opaque blob)**:
   - в storage сохраняется только ciphertext (`BLOB/TEXT`), который не интерпретируется бизнес-логикой;
   - plaintext в БД не хранится.
2. **Метаданные секрета**:
   - operational metadata (например: `key_version`, `created_at`, `updated_at`, `run_id`) хранится отдельно и используется для поиска/маршрутизации/аудита;
   - пользовательские `tags` допускаются снаружи только если они не содержат чувствительных данных;
   - чувствительные/семантические метаданные (если появляются) упаковываются внутрь зашифрованного payload вместе с секретом.

Правило доверия к metadata:
- `key_version` используется как подсказка для выбора ключа, но не как единственный источник истины;
- валидность данных подтверждается только успешной crypto-проверкой (Fernet HMAC) и доменной обработкой ошибок.

### Контракт locator

- Locator строится детерминированно из:
  - `dataset`,
  - `field`,
  - canonical `source_ref` (стабильная сортировка ключей + нормализация пустых значений).
- В storage сохраняется только `locator_hash`; raw `source_ref` в vault не хранится.
- Один и тот же вход всегда даёт один и тот же hash в enrich и apply.
- При несовместимой смене locator-политики требуется явная миграция.

### Поток данных

```
(enrich) secret_candidates
    ↓ SecretStoreProtocol
SecretVaultWriteService
    ↓ locator_hash(dataset + field + canonical source_ref)
SecretCipherPort.encrypt(plaintext, DEK)
    ↓
SecretVaultRepositoryPort.put_secret(ciphertext, key_version)

(apply) PlanItem.secret_fields
    ↓ SecretProviderProtocol
SecretVaultReadService
    ↓ locator_hash(dataset + field + canonical source_ref)
SecretVaultRepositoryPort.get_secret(...)
    ↓
SecretCipherPort.decrypt(ciphertext, DEK)
    ↓
payload hydration
```

### Номенклатура портов (оценка ренейминга)

**Оценка необходимости ренейминга**:
- `SecretProviderProtocol` и `SecretStoreProtocol` уже читаемы и закреплены в pipeline/apply контрактах.
- Их массовый ренейминг сейчас даст высокий churn в коде и тестах без функционального выигрыша.

**Принятое решение по ренеймингу**:
- На внешнем контуре **ренейминг не обязателен** (оставляем текущие имена).
- Для внутренней консистентности вводятся более узкие порты (`SecretCipherPort`, `SecretVaultRepositoryPort`, `VaultKeyProviderPort`).
- Возможный будущий косметический rename внешних портов (`SecretReadPort/SecretWritePort`) рассматривается как низкоприоритетный и не блокирует реализацию.

### Ключи и lifecycle

- Master keys: `ANKEY_VAULT_MASTER_KEYS` (CSV-список, первый — активный).
- Ротация мастер-ключа: re-wrap только DEK.
- Ротация DEK: отдельная операция с re-encrypt секретных записей.
- Ключи не генерируются молча в production режиме.

### Startup readiness (key/vault guard)

- На старте `VaultStartupGuard` выполняет fail-fast проверки:
  1. синтаксис и доступность master keys из ENV;
  2. чтение/инициализация DEK;
  3. чтение и дешифрование служебной probe-записи (`vault.system.healthcheck`).
- Если probe-записи нет, guard создаёт её и сразу проверяет decrypt.
- При ошибке дешифрования/целостности guard завершает запуск до старта клиентских операций.
- Логи содержат только служебные события (`vault_ready`, `key_validation_failed`) без ключей/plaintext.

### Error model (доменные ошибки)

- `SecretKeyConfigError` — неверная конфигурация ключей/ENV.
- `VaultStartupKeyValidationError` — startup guard не прошёл (ключ не подходит к probe-записи).
- `SecretDecryptionError` — ciphertext нельзя расшифровать валидным ключевым набором.
- `SecretIntegrityError` — нарушена целостность ciphertext/metadata.
- `SecretNotFoundError` — секрет не найден по locator (дальше маппится в `SECRET_REQUIRED` на apply boundary).

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Чёткое разделение ответственности (storage != crypto != orchestration).
- ✅ Backend можно заменить без изменений в domain/usecases.
- ✅ Envelope encryption снижает стоимость ротации master-key.
- ✅ SQLite backend минимизирует интеграционный риск на текущем этапе.
- ✅ Формализуется поведение apply при отсутствии `secret_fields` (поле не уходит в payload).
- ✅ Устраняется plaintext runtime-путь.

**Недостатки (компромиссы)**:
- ⚠️ Реализация сложнее, чем «просто Fernet в CSV», но это приемлемо для production-целей.
- ⚠️ Появляется дополнительный слой сервисов/портов, но это осознанная цена за изоляцию.

**Альтернативы, которые отклонили**:
- ❌ **CSV + inline encryption**: не даёт устойчивого операционного контура.
- ❌ **Single-key без envelope**: ротация master-key дорогая (перешифровка всей базы).
- ❌ **Сразу внешний Vault/KMS**: избыточная сложность на текущем этапе внедрения.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/ports/secrets/provider.py` | Сохраняется внешний контракт pipeline/apply |
| `connector/domain/ports/secrets/` | Добавляются crypto/storage/key-provider порты |
| `connector/domain/secrets/` | Добавляются `SecretVaultWriteService`, `SecretVaultReadService`, `SecretLocatorService`, `VaultStartupGuard` |
| `connector/infra/secrets/file_vault_provider.py` | Удалён после завершения миграции на SQLite envelope vault |
| `connector/infra/secrets/` | Добавляются `fernet_envelope_cipher.py`, `sqlite/db.py`, `sqlite/repository.py`, `sqlite/schema.py`, `env_key_provider.py` |
| `connector/delivery/cli/bootstrap.py` | `--vault-mode on/auto` -> vault provider + startup guard |
| `connector/datasets/apply_adapter.py` | Учитывает политику omit secret field when not configured |

### Ключевые методы

- `SecretVaultWriteService.put_many(...)` — запись секретов через locator + encryption.
- `SecretVaultReadService.get_secret(...)` — чтение и дешифрование по locator.
- `SecretLocatorService.build_locator_hash(...)` — единый канонический locator для enrich/apply.
- `VaultStartupGuard.ensure_ready(...)` — fail-fast startup проверка ключей и probe-записи.
- `FernetEnvelopeCipher.decrypt(...)` — детерминированная маппинг-обработка crypto ошибок.

### Инварианты

1. Секреты в хранилище — только ciphertext.
2. Тело секрета в storage всегда непрозрачный blob; бизнес-логика не зависит от его внутреннего формата.
3. Внешние metadata не должны содержать секрет или его реконструируемые части.
4. Ключи никогда не логируются и не попадают в отчёты.
5. Crypto/Integrity ошибки всегда маппятся в доменные ошибки (`SecretDecryptionError`, `SecretIntegrityError`).
6. Если поле не в `secret_fields` операции, поле не формируется в payload.
7. Доступ к vault из pipeline идёт только через порты, без прямых infra-зависимостей.
8. Vault-операции не используют cache role-порты.
9. Приложение не стартует в `vault`-режиме, если startup guard не прошёл key/decrypt проверку.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit: encrypt/decrypt roundtrip + invalid token + wrong key.
- ✅ Unit: SQLite repository CRUD + last-write-wins + run_id фильтрация.
- ✅ Unit: mapping ошибок в `SecretDecryptionError`/`SecretIntegrityError`.
- ✅ Unit: `OperationApplyAdapter` не включает secret field в payload, если поле не в `secret_fields`.
- ✅ Unit: `SecretLocatorService` детерминированно строит одинаковый hash для эквивалентных `source_ref`.
- ✅ Unit: `VaultStartupGuard` (probe create/read, wrong key -> `VaultStartupKeyValidationError`).
- ✅ Integration: `enrich -> plan -> apply` для create/update с vault backend.
- ✅ Migration: CSV -> SQLite vault one-shot команда.

**Проверка в production**:
1. Развернуть с `ANKEY_VAULT_MASTER_KEYS`.
2. Убедиться, что startup guard проходит до старта команд.
3. Выполнить `import plan/apply` для датасета с секретами.
4. Проверить БД: нет plaintext секретов.
5. Проверить ротацию master key (DEK re-wrap).

**Метрики успеха**:
- Количество plaintext секретов в хранилище: `0`.
- Количество необработанных crypto исключений: `0`.
- Ошибки startup из-за неверного ключа обнаруживаются до запуска pipeline: `100%`.

---

## 📐 Диаграммы

**UML диаграммы** (планируемые к добавлению):
- [Vault Sequence](../../uml/transform/enricher/enricher_sequence.puml)
- [Vault Activity](../../uml/transform/enricher/enricher_activity.puml)

**Примеры использования**:

```python
# write path
a_store.put_many(dataset="employees", match_key="Doe|John|M|100", secrets={"password": "..."})

# read path
secret = a_provider.get_secret(dataset="employees", field="password", source_ref={"match_key": "Doe|John|M|100"})
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Первый этап ограничен SQLite backend (осознанно).
- Для датасетов без `match_key` потребуется явный locator-policy в DSL (расширение контракта).

**Риски**:
- ⚠️ Ошибка настройки `ANKEY_VAULT_MASTER_KEYS` может заблокировать decrypt.
  - **Митигация**: fail-fast при старте + явный `SecretKeyConfigError`.
- ⚠️ Неполная миграция legacy CSV может дать misses на apply.
  - **Митигация**: отдельная idempotent команда миграции + отчёт по coverage.
- ⚠️ Несогласованная смена locator-политики приведёт к массовым `not found`.
  - **Митигация**: версионирование locator-policy + миграция индексов/ключей.

### Runbook (операционная фиксация)

1. **Ротация master-key**:
   - добавить новый ключ первым в `ANKEY_VAULT_MASTER_KEYS`;
   - запустить `rewrap_dek`;
   - сохранить старые ключи в хвосте до завершения rollout;
   - после подтверждения удалить устаревшие ключи.
2. **Ротация DEK**:
   - сгенерировать новый DEK;
   - выполнить batch re-encrypt для всех secret-записей;
   - обновить `dek_version`.
3. **Startup key incident**:
   - при `VaultStartupKeyValidationError` блокировать запуск;
   - проверить порядок/валидность ключей в ENV;
   - восстановить ключевой набор и повторить readiness-check.

### Delivery phases

1. **Phase 1 (MVP)**:
   - реализовать минимальный vault backend в отдельном файле `cache/ankey_vault.sqlite3`;
   - не блокировать внедрение vault ожиданием общего refactor multi-DB инфраструктуры.
2. **Phase 2 (platform/architecture)**:
   - унифицировать регистрацию и подключение нескольких DB-файлов в единой инфраструктурной модели;
   - применить общий подход к cache/vault и следующим persistence-компонентам.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `EnricherCore` | Косвенное | Использовать новую store-реализацию через порт |
| `OperationApplyAdapter` | Прямое | Omit policy для неиспользуемых secret fields |
| `ImportPlanService` | Косвенное | wiring нового vault store |
| `import_apply` CLI | Прямое | vault-only режим без prompt fallback |
| `cache sqlite schema` | Прямое | таблицы/индексы vault + миграция версии |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [VAULT-PROBLEM-001](./VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md)
- ✅ [INDEX.md](../INDEX.md) — добавлен раздел Vault
- ✅ [vault-core.md](../../dev/layers/vault/vault-core.md) — бизнес-логика и runtime-контур secret lifecycle
- ⏳ Планируется: UML для storage/crypto flow

---

## 🔗 Связанные документы

- [VAULT-PROBLEM-001](./VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md)
- [TARGET-DEC-003](../target/TARGET-DEC-003-target-core.md)
- [DSL-DEC-004](../dsl/DSL-DEC-004-standardized-compile-contract.md)
- [Resolve DSL](../../dev/layers/resolver/resolve-dsl.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-18 | Решение предложено |
| 2026-02-18 | Решение принято после обсуждения |
