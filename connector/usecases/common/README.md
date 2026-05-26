# connector/usecases/common

## Назначение

Общие утилиты, переиспользуемые несколькими use case'ами.

## Файлы

| Файл | Назначение |
|---|---|
| `identity_sync.py` | `IdentityIndexSyncer` — post-apply синхронизация: обновляет identity-индекс и закрывает pending-ссылки после успешной записи в целевую систему |

## Зависимости

**Зависит от:** `domain/ports/cache/roles.py` (`ApplyRuntimePort`), `domain/transform/matcher/identity_keys.py`.  
**Используется:** `usecases/import_apply_service.py`.
