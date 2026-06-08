# connector/infra/secrets/management

## Назначение

Инфраструктурная защита admin-операций vault. Проверяет, что операции ротации/rewrap выполняются только с корректным admin-паролем.

## Файлы

| Файл | Назначение |
|---|---|
| `admin_password_gate.py` | `AdminPasswordGate` — верифицирует admin-пароль через Argon2id hash; во время интерактивного prompt suppress-ит observability console mirror через `InteractiveIoGate` |

## Зависимости

**Зависит от:** `argon2-cffi`, `connector/common/interactive_io.py`.
**Используется:** `delivery/cli/containers.py` и `delivery/commands/vault_management.py`.
