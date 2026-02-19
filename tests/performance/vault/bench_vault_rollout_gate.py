"""Benchmark harness Stage-09 для vault rollout gate.

Формирует:
- JSON-артефакт с воспроизводимыми метаданными и числовыми метриками.
- Markdown summary для операционного ревью.
- Опциональный verdict baseline comparison с threshold gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, time
from typing import Any

from cryptography.fernet import Fernet

from connector.common.time import getUtcNowIso
from connector.datasets.employees.spec import make_employees_spec
from connector.delivery.commands.import_apply_dry_run_executor import DryRunExecutor
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.secrets.errors import SecretReadError, SecretStoreError
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.infra.secrets.benchmark_gate import (
    BenchmarkGateThresholds,
    build_markdown_summary,
    compare_baseline,
    flatten_numeric_metrics,
)
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository, VaultSqliteDb
from connector.usecases.import_apply_service import ImportApplyService


def main() -> int:
    args = _parse_args()
    run_id = args.run_id or f"vault-bench-{int(time())}"
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    loops = _loops_from_args(args)
    metrics = _run_benchmarks(loops=loops)
    thresholds = BenchmarkGateThresholds(
        regression_threshold_pct=args.regression_threshold_pct,
        busy_timeout_rate_threshold_pct=args.busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=args.schema_changed_rate_threshold_pct,
    )

    current_flat = flatten_numeric_metrics(metrics)
    baseline_compare: dict[str, Any] = {"gate_passed": True, "comparisons": []}
    if args.baseline:
        baseline_payload = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        baseline_flat = flatten_numeric_metrics(baseline_payload.get("metrics", {}))
        baseline_compare = compare_baseline(
            current_metrics=current_flat,
            baseline_metrics=baseline_flat,
            thresholds=thresholds,
        )

    artifact = {
        "meta": {
            "run_id": run_id,
            "git_commit": _git_commit(),
            "generated_at_utc": getUtcNowIso(),
            "profile": "fast" if args.fast else "full",
            "loops": loops,
        },
        "metrics": metrics,
        "baseline_compare": baseline_compare,
    }

    json_path = out_dir / f"vault_benchmark_{run_id}.json"
    md_path = out_dir / f"vault_benchmark_{run_id}.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown_summary(artifact), encoding="utf-8")

    print(f"benchmark_json={json_path}")
    print(f"benchmark_md={md_path}")
    print(f"gate_passed={baseline_compare.get('gate_passed', True)}")

    return 0 if baseline_compare.get("gate_passed", True) else 1


def _run_benchmarks(*, loops: dict[str, int]) -> dict[str, Any]:
    master_key = Fernet.generate_key().decode("utf-8")
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}"})
    cipher = FernetEnvelopeCipher()
    locator = SecretLocatorService()

    crypto = _bench_crypto(cipher=cipher, loops=loops["crypto"])

    with tempfile.TemporaryDirectory(prefix="vault-bench-") as tmp_dir:
        db_path = str(Path(tmp_dir) / "ankey_vault.sqlite3")
        with _open_repo(db_path=db_path) as repository:
            writer = SecretVaultWriteService(
                repository=repository,
                cipher=cipher,
                key_provider=key_provider,
                locator=locator,
            )
            reader = SecretVaultReadService(
                repository=repository,
                cipher=cipher,
                key_provider=key_provider,
                locator=locator,
                default_run_id="bench",
            )
            repository_metrics = _bench_repository(writer=writer, reader=reader, loops=loops["repository"])
            e2e_metrics = _bench_e2e_apply(
                writer=writer,
                repository=repository,
                cipher=cipher,
                key_provider=key_provider,
                locator=locator,
                loops=loops["e2e"],
            )
        contention_metrics = _bench_contention(
            db_path=db_path,
            key_provider=key_provider,
            cipher=cipher,
            locator=locator,
            loops=loops["contention"],
            workers=max(2, loops["contention_workers"]),
        )

    return {
        "crypto": crypto,
        "repository": repository_metrics,
        "e2e": e2e_metrics,
        "contention": contention_metrics,
    }


def _bench_crypto(*, cipher: FernetEnvelopeCipher, loops: int) -> dict[str, float]:
    dek = Fernet.generate_key()
    encrypt_samples: list[float] = []
    decrypt_samples: list[float] = []
    encrypt_started = perf_counter()
    ciphertexts: list[bytes | str] = []
    for idx in range(loops):
        t0 = perf_counter()
        ciphertext = cipher.encrypt(
            plaintext=f"vault-secret-{idx}",
            dek_plaintext=dek,
            cipher_algo="FERNET_V1",
        )
        encrypt_samples.append((perf_counter() - t0) * 1000.0)
        ciphertexts.append(ciphertext)
    encrypt_total_s = max(perf_counter() - encrypt_started, 1e-9)

    decrypt_started = perf_counter()
    for ciphertext in ciphertexts:
        t0 = perf_counter()
        _ = cipher.decrypt(
            ciphertext=ciphertext,
            dek_plaintext=dek,
            cipher_algo="FERNET_V1",
        )
        decrypt_samples.append((perf_counter() - t0) * 1000.0)
    decrypt_total_s = max(perf_counter() - decrypt_started, 1e-9)

    return {
        "encrypt_p50_ms": _percentile(encrypt_samples, 50.0),
        "encrypt_p95_ms": _percentile(encrypt_samples, 95.0),
        "encrypt_ops_sec": loops / encrypt_total_s,
        "decrypt_p50_ms": _percentile(decrypt_samples, 50.0),
        "decrypt_p95_ms": _percentile(decrypt_samples, 95.0),
        "decrypt_ops_sec": loops / decrypt_total_s,
    }


def _bench_repository(
    *,
    writer: SecretVaultWriteService,
    reader: SecretVaultReadService,
    loops: int,
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for batch_size in (1, 10, 100):
        samples: list[float] = []
        started = perf_counter()
        for idx in range(loops):
            secrets = {f"password_{field}": f"Secret-{idx}-{field}" for field in range(batch_size)}
            t0 = perf_counter()
            writer.put_many(
                dataset="employees",
                match_key=f"repo-match-{batch_size}-{idx}",
                secrets=secrets,
                run_id="bench",
            )
            samples.append((perf_counter() - t0) * 1000.0)
        total_s = max(perf_counter() - started, 1e-9)
        metrics[f"put_many_batch_{batch_size}_p95_ms"] = _percentile(samples, 95.0)
        metrics[f"put_many_batch_{batch_size}_ops_sec"] = loops / total_s

    writer.put_many(
        dataset="employees",
        match_key="repo-lookup-key",
        secrets={"password": "LookupSecret"},
        run_id="bench",
    )
    warm_samples: list[float] = []
    warm_started = perf_counter()
    for _ in range(loops):
        t0 = perf_counter()
        value = reader.get_secret(
            dataset="employees",
            field="password",
            source_ref={"match_key": "repo-lookup-key"},
            run_id="bench",
        )
        assert value == "LookupSecret"
        warm_samples.append((perf_counter() - t0) * 1000.0)
    warm_total_s = max(perf_counter() - warm_started, 1e-9)

    cold_samples: list[float] = []
    for idx in range(min(loops, 50)):
        match_key = f"repo-cold-{idx}"
        writer.put_many(
            dataset="employees",
            match_key=match_key,
            secrets={"password": f"ColdSecret-{idx}"},
            run_id="bench",
        )
        t0 = perf_counter()
        value = reader.get_secret(
            dataset="employees",
            field="password",
            source_ref={"match_key": match_key},
            run_id="bench",
        )
        assert value == f"ColdSecret-{idx}"
        cold_samples.append((perf_counter() - t0) * 1000.0)

    metrics["get_secret_warm_p95_ms"] = _percentile(warm_samples, 95.0)
    metrics["get_secret_warm_ops_sec"] = loops / warm_total_s
    metrics["get_secret_cold_p95_ms"] = _percentile(cold_samples, 95.0)
    return metrics


def _bench_e2e_apply(
    *,
    writer: SecretVaultWriteService,
    repository: SqliteVaultRepository,
    cipher: FernetEnvelopeCipher,
    key_provider: EnvVaultKeyProvider,
    locator: SecretLocatorService,
    loops: int,
) -> dict[str, float]:
    row_count = max(50, loops * 40)
    run_id = "bench-e2e"
    for idx in range(row_count):
        writer.put_many(
            dataset="employees",
            match_key=f"e2e-match-{idx}",
            secrets={"password": f"E2E-Secret-{idx}"},
            run_id=run_id,
        )

    provider = SecretVaultReadService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
        default_run_id=run_id,
    )
    spec = make_employees_spec(
        secrets=provider,
    )
    adapter = spec.get_apply_adapter()
    service = ImportApplyService(DryRunExecutor())
    catalog = build_catalog("employees", strict=True)

    samples: list[float] = []
    throughputs: list[float] = []
    for iteration in range(max(1, loops // 2)):
        plan = _build_e2e_plan(row_count=row_count, run_id=run_id, batch_tag=iteration)
        t0 = perf_counter()
        result = service.apply_plan(
            plan=plan,
            catalog=catalog,
            apply_adapter=adapter,
            stop_on_first_error=False,
            max_actions=None,
            max_item_outcomes=20,
        )
        elapsed = max(perf_counter() - t0, 1e-9)
        assert result.summary.failed == 0
        samples.append(elapsed * 1000.0)
        throughputs.append(row_count / elapsed)

    return {
        "apply_p95_ms": _percentile(samples, 95.0),
        "apply_throughput_rows_sec": _percentile(throughputs, 50.0),
    }


def _bench_contention(
    *,
    db_path: str,
    key_provider: EnvVaultKeyProvider,
    cipher: FernetEnvelopeCipher,
    locator: SecretLocatorService,
    loops: int,
    workers: int,
) -> dict[str, float]:
    # Подготовить читаемый ключ/секрет до конкурентной нагрузки.
    with _open_repo(db_path=db_path) as seed_repo:
        seed_writer = SecretVaultWriteService(
            repository=seed_repo,
            cipher=cipher,
            key_provider=key_provider,
            locator=locator,
        )
        seed_writer.put_many(
            dataset="employees",
            match_key="contention-key",
            secrets={"password": "seed"},
            run_id="bench",
        )

    busy_timeout = 0
    schema_changed = 0
    total_ops = max(1, loops)
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _contention_op,
                idx=idx,
                db_path=db_path,
                key_provider=key_provider,
                cipher=cipher,
                locator=locator,
            )
            for idx in range(total_ops)
        ]
        for fut in as_completed(futures):
            reason = fut.result()
            if reason == "busy_timeout":
                busy_timeout += 1
            elif reason == "schema_changed":
                schema_changed += 1
    elapsed = max(perf_counter() - started, 1e-9)

    return {
        "ops_sec": total_ops / elapsed,
        "busy_timeout_rate_pct": _pct(busy_timeout, total_ops),
        "schema_changed_rate_pct": _pct(schema_changed, total_ops),
    }


def _contention_op(
    *,
    idx: int,
    db_path: str,
    key_provider: EnvVaultKeyProvider,
    cipher: FernetEnvelopeCipher,
    locator: SecretLocatorService,
) -> str | None:
    with _open_repo(db_path=db_path) as repo:
        writer = SecretVaultWriteService(
            repository=repo,
            cipher=cipher,
            key_provider=key_provider,
            locator=locator,
        )
        reader = SecretVaultReadService(
            repository=repo,
            cipher=cipher,
            key_provider=key_provider,
            locator=locator,
            default_run_id="bench",
        )
        try:
            if idx % 2 == 0:
                writer.put_many(
                    dataset="employees",
                    match_key=f"contention-w-{idx}",
                    secrets={"password": f"w-{idx}"},
                    run_id="bench",
                )
                return None
            _ = reader.get_secret(
                dataset="employees",
                field="password",
                source_ref={"match_key": "contention-key"},
                run_id="bench",
            )
            return None
        except SecretStoreError as exc:
            return str((exc.details or {}).get("reason") or "store_error")
        except SecretReadError as exc:
            return str((exc.details or {}).get("reason") or "read_error")


@contextmanager
def _open_repo(*, db_path: str):
    db = VaultSqliteDb(db_path=db_path)
    try:
        yield SqliteVaultRepository(db)
    finally:
        db.close()


def _build_e2e_plan(*, row_count: int, run_id: str, batch_tag: int) -> Plan:
    items: list[PlanItem] = []
    for idx in range(row_count):
        items.append(
            PlanItem(
                row_id=f"row-{batch_tag}-{idx}",
                line_no=idx + 1,
                op="create",
                target_id=f"target-{idx}",
                desired_state=_base_state(idx),
                changes={},
                source_ref={"match_key": f"e2e-match-{idx}"},
                secret_fields=["password"],
            )
        )
    return Plan(
        meta=PlanMeta(
            run_id=run_id,
            generated_at=None,
            dataset="employees",
            csv_path=None,
            plan_path=None,
            include_deleted=False,
        ),
        summary=PlanSummary(
            rows_total=row_count,
            valid_rows=row_count,
            failed_rows=0,
            planned_create=row_count,
            planned_update=0,
            skipped=0,
        ),
        items=items,
    )


def _base_state(idx: int) -> dict[str, object]:
    return {
        "email": f"user-{idx}@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": f"user-{idx}",
        "phone": f"+1000{idx:04d}",
        "password": "",
        "personnel_number": str(1000 + idx),
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": f"TAB-{idx}",
    }


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = int(round(((pct / 100.0) * (len(ordered) - 1))))
    rank = max(0, min(rank, len(ordered) - 1))
    return ordered[rank]


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (float(count) / float(total)) * 100.0


def _git_commit() -> str:
    try:
        raw = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True)
    except Exception:
        return "unknown"
    return raw.strip() or "unknown"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Запустить benchmark gate для vault rollout.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default="reports/vault-benchmarks")
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--regression-threshold-pct", type=float, default=15.0)
    parser.add_argument("--busy-timeout-rate-threshold-pct", type=float, default=0.0)
    parser.add_argument("--schema-changed-rate-threshold-pct", type=float, default=0.0)
    return parser.parse_args()


def _loops_from_args(args: argparse.Namespace) -> dict[str, int]:
    if args.fast:
        return {
            "crypto": 200,
            "repository": 60,
            "e2e": 6,
            "contention": 80,
            "contention_workers": 4,
        }
    return {
        "crypto": 2000,
        "repository": 300,
        "e2e": 20,
        "contention": 600,
        "contention_workers": 8,
    }


if __name__ == "__main__":
    raise SystemExit(main())
