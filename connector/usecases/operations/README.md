# connector/usecases/operations

## Назначение

Legacy re-export модуль для обратной совместимости. Перенаправляет импорты vault key management из `connector.usecases.operations.vault_key_management` → `connector.usecases.management.vault`.

## Файлы

| Файл | Назначение |
|---|---|
| `vault_key_management.py` | Re-exports `VaultKeyManagementUseCase`, `VaultKeyManagementResult`, `VaultKeyManagementStatus` и сопутствующих типов из `usecases/management/vault/` |
| `vault_management_settings.py` | Re-exports настроек vault management |

## Зависимости

Не содержит собственной реализации — только `from connector.usecases.management.vault import ...`.  
**Используется:** устаревшим кодом, ссылающимся на старый путь импорта.
