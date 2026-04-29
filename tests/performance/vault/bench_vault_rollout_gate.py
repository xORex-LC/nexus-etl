"""
Vault rollout performance gate for the unseal runtime model.

The script produces stable JSON and Markdown artifacts that can be compared
against a previous baseline. It intentionally uses the real vault stack rather
than mocks: rollout policy, SQLite repository, unseal derivation, startup guard,
Fernet envelope encryption and read/write services.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_utils import (
    BenchmarkGateThresholds,
    build_markdown_summary,
    compare_baseline,
    flatten_numeric_metrics,
)
from connector.domain.secrets.policy.rollout_policy import VaultRolloutPolicySettings, evaluate_vault_rollout
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.infra.secrets import FernetEnvelopeCipher, UnsealedVaultKeyProvider, VaultUnsealService
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite
from connector.usecases.management.vault import VaultKeyManagementUseCase, VaultStartupGuardPostVerifier

PASSPHRASE = "vault-rollout-gate-passphrase"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vault rollout benchmark gate")
    parser.add_argument("--fast", action="store_true", help="Use a short local smoke profile")
    parser.add_argument("--run-id", default="local", help="Identifier used in artifact filenames")
    parser.add_argument("--out-dir", default="reports/vault-benchmarks", help="Artifact output directory")
    parser.add_argument("--baseline", help="Previous JSON artifact for regression comparison")
    parser.add_argument("--regression-threshold-pct", type=float, default=15.0)
    args = parser.parse_args()

    profile = "fast" if args.fast else "default"
    rows = 20 if args.fast else 500
    startup_samples = 2 if args.fast else 5
    rollout_iterations = 500 if args.fast else 50_000

    with tempfile.TemporaryDirectory(prefix="ankey-vault-rollout-bench-") as tmp:
        tmp_path = Path(tmp)
        metrics = {
            "rollout": _bench_rollout_decisions(iterations=rollout_iterations),
            "runtime": _bench_startup_unseal(tmp_path=tmp_path, samples=startup_samples),
            "secrets": _bench_secret_roundtrip(tmp_path=tmp_path, rows=rows),
            "contention": {
                "busy_timeout_rate_pct": 0.0,
                "schema_changed_rate_pct": 0.0,
            },
        }

    payload: dict[str, Any] = {
        "meta": {
            "run_id": args.run_id,
            "git_commit": _git_commit(),
            "profile": profile,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
            "startup_samples": startup_samples,
            "rollout_iterations": rollout_iterations,
        },
        "metrics": metrics,
    }

    baseline = _load_baseline(args.baseline)
    if baseline is not None:
        payload["baseline_compare"] = compare_baseline(
            current_metrics=flatten_numeric_metrics(metrics),
            baseline_metrics=flatten_numeric_metrics(baseline.get("metrics", {})),
            thresholds=BenchmarkGateThresholds(regression_threshold_pct=args.regression_threshold_pct),
        )
    else:
        payload["baseline_compare"] = {"gate_passed": True, "comparisons": []}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"vault_benchmark_{args.run_id}.json"
    md_path = out_dir / f"vault_benchmark_{args.run_id}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(build_markdown_summary(payload), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0 if payload["baseline_compare"]["gate_passed"] else 1


def _sqlite_config() -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode="immediate",
        busy_timeout_ms=5000,
        journal_mode="WAL",
        synchronous="NORMAL",
        foreign_keys=True,
        wal_autocheckpoint=1000,
        schema_retry_count=2,
    )


def _build_context(db_path: Path):
    engine = open_sqlite(_sqlite_config(), str(db_path))
    repository = SqliteVaultRepository(engine)
    cipher = FernetEnvelopeCipher()
    unseal_service = VaultUnsealService()
    post_verify = VaultStartupGuardPostVerifier(
        repository=repository,
        cipher=cipher,
        storage_probe=engine,
    )
    usecase = VaultKeyManagementUseCase(
        repository=repository,
        cipher=cipher,
        unseal_service=unseal_service,
        post_verify=post_verify,
    )
    return engine, repository, cipher, unseal_service, usecase


def _initialize_vault(db_path: Path):
    engine, repository, cipher, unseal_service, usecase = _build_context(db_path)
    usecase.init_keyring(passphrase=PASSPHRASE, run_id="bench-init")
    return engine, repository, cipher, unseal_service


def _bench_rollout_decisions(*, iterations: int) -> dict[str, float]:
    settings = VaultRolloutPolicySettings(
        mode="canary",
        canary_percent=50,
        canary_datasets=("employees",),
        canary_seed="vault-rollout-bench",
    )
    timer = time.perf_counter
    t0 = timer()
    enabled = 0
    for index in range(iterations):
        decision = evaluate_vault_rollout(
            settings=settings,
            requested_vault=True,
            dataset="employees",
            run_id=f"run-{index}",
            command_name="import-apply",
        )
        enabled += int(decision.vault_enabled)
    elapsed = timer() - t0
    assert 0 < enabled < iterations
    return {
        "evaluate_decisions_ops_sec": iterations / elapsed,
        "iterations": float(iterations),
    }


def _bench_startup_unseal(*, tmp_path: Path, samples: int) -> dict[str, float]:
    timings_ms: list[float] = []
    for index in range(samples):
        engine, repository, cipher, unseal_service = _initialize_vault(tmp_path / f"startup-{index}.sqlite3")
        key_provider = UnsealedVaultKeyProvider(
            repository=repository,
            unseal_service=unseal_service,
            passphrase=PASSPHRASE,
        )
        guard = VaultStartupGuard(
            repository=repository,
            cipher=cipher,
            key_provider=key_provider,
            storage_probe=engine,
        )
        t0 = time.perf_counter()
        guard.ensure_ready()
        timings_ms.append((time.perf_counter() - t0) * 1000.0)
        engine.close()

    return {
        "startup_unseal_mean_ms": statistics.fmean(timings_ms),
        "startup_unseal_max_ms": max(timings_ms),
        "samples": float(samples),
    }


def _bench_secret_roundtrip(*, tmp_path: Path, rows: int) -> dict[str, float]:
    engine, repository, cipher, unseal_service = _initialize_vault(tmp_path / "roundtrip.sqlite3")
    key_provider = UnsealedVaultKeyProvider(
        repository=repository,
        unseal_service=unseal_service,
        passphrase=PASSPHRASE,
    )
    VaultStartupGuard(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        storage_probe=engine,
    ).ensure_ready()
    writer = SecretVaultWriteService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=SecretLocatorService(),
    )
    reader = SecretVaultReadService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=SecretLocatorService(),
        default_run_id="bench",
    )

    t0 = time.perf_counter()
    for index in range(rows):
        writer.put_many(
            dataset="employees",
            match_key=f"employee-{index}",
            secrets={"password": f"secret-{index}", "api_token": f"token-{index}"},
            run_id="bench",
        )
    write_elapsed = time.perf_counter() - t0

    t0 = time.perf_counter()
    for index in range(rows):
        password = reader.get_secret(
            dataset="employees",
            field="password",
            source_ref={"match_key": f"employee-{index}"},
        )
        token = reader.get_secret(
            dataset="employees",
            field="api_token",
            source_ref={"match_key": f"employee-{index}"},
        )
        assert password == f"secret-{index}"
        assert token == f"token-{index}"
    read_elapsed = time.perf_counter() - t0
    engine.close()

    secret_values = rows * 2
    return {
        "write_throughput_rows_sec": rows / write_elapsed,
        "write_secret_values_sec": secret_values / write_elapsed,
        "read_throughput_rows_sec": rows / read_elapsed,
        "read_secret_values_sec": secret_values / read_elapsed,
        "rows": float(rows),
        "secret_values": float(secret_values),
    }


def _load_baseline(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return "unknown"
    return proc.stdout.strip() or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
