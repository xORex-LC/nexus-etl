# connector/usecases/management/vault

## Назначение

Оркестрация lifecycle-операций vault: инициализация, проверка статуса, ротация мастер-ключа, rewrap DEK. Не знает об SQLite, CLI-промптах или конкретном алгоритме шифрования.

## Файлы

| Файл | Назначение |
|---|---|
| `usecase.py` | `VaultKeyManagementUseCase` — методы: `init(password)`, `status()`, `rotate(old_pw, new_pw)`, `rewrap(old_pw)` |
| `contracts.py` | Протоколы фабрик: `KeyVersionFactory`, `NowFactory`, `RunIdFactory`, `VaultPostVerifyProtocol`, `VaultUnsealServiceProtocol` |
| `models.py` | `VaultKeyManagementResult`, `VaultKeyManagementStatus` — результаты операций |
| `verify.py` | `VaultStartupGuardPostVerifier` — post-verify hook после init/rotate |

## Операции

| Команда | Действие |
|---|---|
| `init` | Создаёт probe, DEK, сохраняет мета в vault |
| `status` | Проверяет probe, выводит мета (версия ключа, timestamp) |
| `rotate` | Создаёт новый master key, перешифровывает DEK |
| `rewrap` | Перешифровывает DEK с текущим master key (без смены пароля) |

## Зависимости

**Зависит от:** `domain/ports/secrets/`, `domain/secrets/services.py`, `domain/secrets/models.py`, `infra/secrets/management/` (через DI).  
**Используется:** `delivery/commands/vault_management.py`.
