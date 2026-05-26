# connector/usecases/management

## Назначение

Административные use case'ы для управления инфраструктурными компонентами (vault, и потенциально другие в будущем).

## Структура

| Подпапка | Назначение |
|---|---|
| `vault/` | `VaultKeyManagementUseCase` — init, status, rotate, rewrap vault |

## Зависимости

**Зависит от:** `domain/ports/secrets/`, `domain/secrets/`.  
**Используется:** `delivery/commands/vault_management.py`.
