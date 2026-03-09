"""
PyPerf benchmark: vault-management lifecycle операции.

Покрывает:
1. `rotate_and_rewrap` latency.
2. `rewrap_all_dek` latency.
3. `VaultMaintenanceUseCase.run_if_due` в no-op режиме.
4. `vault_startup_resource()` overhead.

Запуск:
    .venv/bin/python tests/performance/vault/bench_vault_management_lifecycle_pyperf.py --fast
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import tempfile
from typing import Iterator

import pyperf
import structlog
from cryptography.fernet import Fernet

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from connector.delivery.cli.containers import vault_startup_resource
from connector.domain.secrets.models import VaultDekRecord
from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval, VaultRotationPolicy
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher
from connector.infra.secrets.env_key_provider import DEFAULT_MASTER_KEYS_ENV
from connector.infra.secrets.management.managed_env_keyring_store import VaultManagedEnvKeyringStore
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.usecases.management.vault import (
    VaultKeyManagementUseCase,
    VaultMaintenanceUseCase,
    VaultStartupGuardPostVerifier,
)


@dataclass
class _LifecycleState:
    engine: SqliteEngine
    repository: SqliteVaultRepository
    cipher: FernetEnvelopeCipher
    keyring_store: VaultManagedEnvKeyringStore
    key_management: VaultKeyManagementUseCase
    maintenance_noop: VaultMaintenanceUseCase

    def close(self) -> None:
        self.engine.close()


def _configure_structlog_for_benchmarks() -> None:
    """Понизить шум логов во время pyperf-прогонов."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )


def _enter_resource(resource: Iterator[None]) -> None:
    """Выполнить enter для generator-resource."""
    next(resource)


def _exit_resource(resource: Iterator[None]) -> None:
    """Выполнить exit для generator-resource."""
    try:
        next(resource)
    except StopIteration:
        return
    raise RuntimeError("Resource generator produced more than one value")


def _build_engine(base_dir: Path) -> SqliteEngine:
    app_config = AppConfig.model_validate(
        {"paths": {"cache_dir": str(base_dir / "cache")}}
    )
    db_path = str(base_dir / "cache" / "ankey_vault.sqlite3")
    return open_sqlite(to_vault_db_config(app_config), db_path)


def _build_state(base_dir: Path) -> _LifecycleState:
    engine = _build_engine(base_dir)
    repository = SqliteVaultRepository(engine)
    cipher = FernetEnvelopeCipher()
    keyring_store = VaultManagedEnvKeyringStore(str(base_dir / "cache" / "vault.env"))
    key_management = VaultKeyManagementUseCase(
        repository=repository,
        cipher=cipher,
        keyring_store=keyring_store,
        post_verify=VaultStartupGuardPostVerifier(
            repository=repository,
            cipher=cipher,
            storage_probe=engine,
        ),
    )

    init_result = key_management.init_keyring()
    active_key = keyring_store.load_keyring()[0]
    assert init_result.active_key_version == active_key.key_version

    # Добавляем ещё один DEK, чтобы rewrap/rotate отражали работу по нескольким записям.
    extra_plain = Fernet.generate_key()
    extra_wrapped = cipher.wrap_dek(
        dek_plaintext=extra_plain,
        master_key=active_key.key_material,
        wrap_algo=FERNET_V1,
    )
    repository.upsert_dek(
        VaultDekRecord(
            dek_version="dek_bench_extra",
            wrapped_dek=extra_wrapped,
            wrap_algo=FERNET_V1,
            wrap_key_version=active_key.key_version,
            is_active=False,
            created_at="2026-03-06T00:00:00+00:00",
            updated_at="2026-03-06T00:00:00+00:00",
        )
    )

    repository.set_last_rotated_at("2026-03-06T00:00:00+00:00")
    maintenance_noop = VaultMaintenanceUseCase(
        key_management=key_management,
        rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
        now_utc=lambda: "2026-03-06T00:00:00+00:00",
    )

    return _LifecycleState(
        engine=engine,
        repository=repository,
        cipher=cipher,
        keyring_store=keyring_store,
        key_management=key_management,
        maintenance_noop=maintenance_noop,
    )


def bench_rotate_and_rewrap(loops: int) -> float:
    timer = pyperf.perf_counter
    with tempfile.TemporaryDirectory(prefix="vault-bench-rotate-") as tmp_dir:
        state = _build_state(Path(tmp_dir))
        try:
            total = 0.0
            for _ in range(loops):
                t0 = timer()
                state.key_management.rotate_and_rewrap()
                total += timer() - t0
            return total
        finally:
            state.close()


def bench_rewrap_all_dek(loops: int) -> float:
    timer = pyperf.perf_counter
    with tempfile.TemporaryDirectory(prefix="vault-bench-rewrap-") as tmp_dir:
        state = _build_state(Path(tmp_dir))
        try:
            total = 0.0
            for _ in range(loops):
                t0 = timer()
                state.key_management.rewrap_all_dek()
                total += timer() - t0
            return total
        finally:
            state.close()


def bench_maintenance_noop(loops: int) -> float:
    timer = pyperf.perf_counter
    with tempfile.TemporaryDirectory(prefix="vault-bench-maintenance-noop-") as tmp_dir:
        state = _build_state(Path(tmp_dir))
        try:
            total = 0.0
            for _ in range(loops):
                t0 = timer()
                result = state.maintenance_noop.run_if_due()
                assert result.action == "no_op"
                total += timer() - t0
            return total
        finally:
            state.close()


def bench_startup_overhead(loops: int) -> float:
    timer = pyperf.perf_counter
    with tempfile.TemporaryDirectory(prefix="vault-bench-startup-") as tmp_dir:
        base_dir = Path(tmp_dir)
        state = _build_state(base_dir)
        state.close()

        app_config = AppConfig.model_validate(
            {
                "paths": {"cache_dir": str(base_dir / "cache")},
                "vault_management": {
                    "managed_env_file": str(base_dir / "cache" / "vault.env"),
                    "auto_rotate_enabled": False,
                },
            }
        )
        db_path = str(base_dir / "cache" / "ankey_vault.sqlite3")
        total = 0.0
        for _ in range(loops):
            os.environ.pop(DEFAULT_MASTER_KEYS_ENV, None)
            engine = open_sqlite(to_vault_db_config(app_config), db_path)
            t0 = timer()
            resource = vault_startup_resource(engine=engine, app_config=app_config)
            _enter_resource(resource)
            total += timer() - t0
            _exit_resource(resource)
        return total


if __name__ == "__main__":
    _configure_structlog_for_benchmarks()
    runner = pyperf.Runner()
    runner.bench_time_func("vault_mgmt_rotate_and_rewrap", bench_rotate_and_rewrap)
    runner.bench_time_func("vault_mgmt_rewrap_all_dek", bench_rewrap_all_dek)
    runner.bench_time_func("vault_mgmt_maintenance_noop", bench_maintenance_noop)
    runner.bench_time_func("vault_mgmt_startup_overhead", bench_startup_overhead)
