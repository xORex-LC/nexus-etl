# connector/infra/target/providers/ankey_rest

## Назначение

Провайдер для Ankey IDM REST API. Собирает полный runtime: HTTP-driver с basic auth (опционально TLS), Ankey-специфичные мутации операций и gateway.

## Файлы

| Файл | Назначение |
|---|---|
| `provider.py` | `AnkeyTargetProvider` — `build_core_runtime()` → `TargetRuntime`; регистрирует driver + mutations + gateway |
| `driver.py` | `AnkeyRestDriver` — реализует `TargetDriver` поверх HTTP-транспорта |
| `auth.py` | `AnkeyAuth` — basic auth для httpx (username/password из `ApiConfig`) |
| `mutations.py` | `build_ankey_mutations()` — Ankey-специфичные переопределения обработки ошибок операций |
| `payloads/` | (зарезервировано для payload-трансформеров) |

## Зависимости

**Зависит от:** `infra/target/core/`, `infra/target/transports/http/`, `config/models.py`.  
**Используется:** `infra/target/core/factory.py`.
