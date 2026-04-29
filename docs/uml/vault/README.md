# Vault UML

Структура:

1. `docs/uml/vault/management`
- Диаграммы vault-management lifecycle. Исторические диаграммы DEC-002 описывают
  managed env keyring; актуальная runtime-модель закреплена в DEC-003 и
  использует команды `init/status/rotate/rewrap` без `delete-key` и
  `run-maintenance`.

Формат хранения:

1. PNG-артефакты лежат в `docs/uml/vault/management/`.
2. Исходники PlantUML лежат в `docs/uml/vault/management/puml/`.
