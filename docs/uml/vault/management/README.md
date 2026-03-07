# Vault Management UML

Набор покрывает фактическую реализацию DEC-002:

- `vault_management_class.*` — классы/протоколы и layer boundaries.
- `vault_management_sequence.*` — ручной `rotate` (crash-safe bridge + rewrap + verify).
- `vault_management_activity.*` — flow `run_if_due` в maintenance usecase.
- `vault_management_state_machine.*` — lifecycle metadata (`rotating|ok|failed`).

Источник модели: текущий код в
`connector/usecases/management/vault/*`,
`connector/delivery/commands/vault_management.py`,
`connector/infra/secrets/management/*`,
`connector/infra/secrets/sqlite/repository.py`.
