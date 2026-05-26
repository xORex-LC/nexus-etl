# connector/infra/target/providers

## Назначение

Конкретные реализации провайдеров целевой системы. Каждый провайдер — полная сборка driver + auth + mutations для одной системы.

## Структура

| Подпапка | Провайдер |
|---|---|
| `ankey_rest/` | Ankey IDM REST API |

## Зависимости

**Зависит от:** `infra/target/core/`, `infra/target/transports/http/`.  
**Используется:** `infra/target/core/factory.py` (по имени провайдера из `TargetSpec`).
