# connector/infra/target/transports

## Назначение

Транспортный слой для взаимодействия с целевой системой. Изолирует детали протокола (HTTP) от ядра gateway.

## Структура

| Подпапка | Назначение |
|---|---|
| `http/` | HTTP-транспорт на базе `httpx` |

## Зависимости

**Зависит от:** `infra/target/core/`.  
**Используется:** `infra/target/providers/ankey_rest/`.
