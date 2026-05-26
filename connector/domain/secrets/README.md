# connector/domain/secrets

## Назначение

Доменная логика жизненного цикла секретов: инициализация vault, ротация ключей, чтение/запись секретов в pipeline, startup-проверки.

## Структура

| Файл/папка | Назначение |
|---|---|
| `models.py` | `VaultSecretRecord`, `VaultDekRecord`, `VaultProbeRecord`, `VaultUnsealMetadata` |
| `errors.py` | `SecretStoreError`, `SecretReadError`, `SecretDecryptionError`, `SecretNotFoundError`, `SecretIntegrityError`, `VaultManagementOperationError` |
| `services.py` | `SecretLocatorService`, `SecretVaultReadService`, `SecretVaultWriteService`, `VaultRetentionService` |
| `startup_guard.py` | `VaultStartupGuard` — проверки при старте: инициализирован ли vault, доступен ли на запись, верна ли probe |
| `policy/` | Политики vault: `RetentionPolicy`, `RolloutPolicy`, `RotationPolicy`, `RuntimeModePolicy` |

## Поток секретов в pipeline

```
EnrichStage → SecretVaultWriteService.put(secret)  # Запись при enrich
ImportApplyService → SecretVaultReadService.get(ref)  # Чтение при apply
```

## Зависимости

**Зависит от:** `domain/ports/secrets/`.  
**Используется:** `domain/transform/enrich/`, `usecases/import_apply_service.py`, `usecases/management/vault/`.
