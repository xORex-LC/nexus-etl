# connector/domain/transform/ids

## Назначение

Value objects для идентификации записей в процессе трансформации.

## Файлы

| Файл | Назначение |
|---|---|
| `match_key.py` | `MatchKey` — value object для ключа сопоставления; `build_delimited_match_key(parts, delimiter, strict)` — строит ключ из нескольких частей через разделитель; `strict=True` → ошибка при None-части |
| `target_id.py` | `TargetId` — value object для идентификатора записи в целевой системе |

## Зависимости

**Зависит от:** stdlib.  
**Используется:** `domain/transform/matcher/`, `domain/transform/resolver/`, `domain/transform/enrich/`.
