# Vault Performance Benchmarks

Набор проверяет текущую unseal runtime модель vault без managed ENV keyring:
runtime вводит passphrase, infra выводит master wrapping key через Argon2id,
а vault read/write path работает через `UnsealedVaultKeyProvider`.

## Rollout Gate

Скрипт пишет JSON/Markdown артефакты и может сравнивать текущий прогон с baseline:

```bash
.venv/bin/python tests/performance/vault/bench_vault_rollout_gate.py --fast --run-id local-fast
```

С baseline comparison:

```bash
.venv/bin/python tests/performance/vault/bench_vault_rollout_gate.py \
  --run-id release-candidate \
  --baseline reports/vault-benchmarks/vault_benchmark_previous.json
```

Артефакты записываются в `reports/vault-benchmarks/`:
- `vault_benchmark_<run_id>.json`
- `vault_benchmark_<run_id>.md`

Метрики:
- `rollout.evaluate_decisions_ops_sec` — скорость принятия rollout/canary решений.
- `runtime.startup_unseal_mean_ms` — startup guard с unseal passphrase, HMAC/Argon2id и probe decrypt.
- `secrets.write_throughput_rows_sec` — запись строк с двумя encrypted secret fields.
- `secrets.read_throughput_rows_sec` — чтение и decrypt строк с двумя secret fields.
- `contention.*_rate_pct` — доля storage contention/schema ошибок в одиночном прогоне.

## Vault Management Lifecycle

Pyperf-бенч для lifecycle-команд:

```bash
.venv/bin/python tests/performance/vault/bench_vault_management_lifecycle_pyperf.py \
  --fast \
  --output reports/vault-benchmarks/vault_mgmt_lifecycle.json
```

Сценарии:
- `vault_management_init` — создание `vault_unseal_meta`, DEK и startup probe.
- `vault_management_status_verify` — проверка passphrase через HMAC/Argon2id и probe.
- `vault_management_rotate_rewrap` — смена passphrase и rewrap DEK.
- `vault_management_rewrap` — rewrap текущим derived key без смены passphrase.

## Smoke

```bash
.venv/bin/python -m pytest -m performance tests/performance/vault -q
```
