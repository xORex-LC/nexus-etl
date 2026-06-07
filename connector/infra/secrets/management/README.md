# connector/infra/secrets/management

## Назначение

Инфраструктурная защита admin-операций vault. Проверяет, что операции ротации/rewrap выполняются только с корректным admin-паролем.

## Файлы

| Файл | Назначение |
|---|---|
| `admin_password_gate.py` | `AdminPasswordGate` — верифицирует admin-пароль через Argon2id hash; блокирует операции при несоответствии |

## Зависимости

**Зависит от:** `argon2-cffi`.  
**Используется:** `usecases/management/vault/usecase.py`.
