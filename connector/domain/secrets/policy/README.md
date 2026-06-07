# connector/domain/secrets/policy

## Назначение

Декларативные политики жизненного цикла секретов в vault.

## Файлы

| Файл | Политика | Что регулирует |
|---|---|---|
| `retention.py` | `RetentionPolicy` | Срок хранения секретов после завершения прогона |
| `rollout.py` | `RolloutPolicy` | Canary-режим ввода новых ключей шифрования |
| `rotation.py` | `RotationPolicy` | Расписание и условия ротации DEK |
| `runtime_mode.py` | `RuntimeModePolicy` | Режим runtime (read-only, read-write) для vault в пайплайне |

## Зависимости

**Зависит от:** stdlib, `domain/secrets/models.py`.  
**Используется:** `domain/secrets/services.py`, `usecases/management/vault/`.
