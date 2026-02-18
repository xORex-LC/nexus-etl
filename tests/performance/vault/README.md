# Vault Rollout Benchmark Gate

Benchmark harness Stage-09:

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
