from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.loader import load_enrich_spec_for_dataset, load_sink_spec_for_dataset
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.enrich import EnricherEngine
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.diagnostics.catalog import build_catalog
from connector.config.app_settings import SqliteSettings, build_vault_db_config
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine


@dataclass
class _DummyEnrichDeps:
    cache_gateway: object
    identity_lookup = None


class _EmptyCacheRepo:
    def find(
        self,
        dataset: str,
        filters: dict[str, object],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ):
        _ = (dataset, filters, include_deleted, mode)
        return []

    def find_one(
        self,
        dataset: str,
        filters: dict[str, object],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ):
        _ = (dataset, filters, include_deleted, mode)
        return None


def _build_store(tmp_path: Path):
    master_key = Fernet.generate_key().decode("utf-8")
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}"})
    cipher = FernetEnvelopeCipher()
    locator = SecretLocatorService()
    engine = open_sqlite(
        build_vault_db_config(SqliteSettings()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    repository = SqliteVaultRepository(engine)
    store = SecretVaultWriteService(
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )
    return store, repository, locator, key_provider, cipher, engine


def _build_enricher(secret_store: SecretVaultWriteService) -> EnricherEngine:
    catalog = build_catalog("employees", strict=True)
    registry = OperationRegistry()
    register_core_ops(registry)
    return EnricherEngine(
        spec=load_enrich_spec_for_dataset("employees"),
        deps=_DummyEnrichDeps(cache_gateway=_EmptyCacheRepo()),
        secret_store=secret_store,
        dataset="employees",
        catalog=catalog,
        registry=registry,
        options=EnrichDslBuildOptions(require_match_key=True),
        sink_spec=load_sink_spec_for_dataset("employees"),
        run_id="run-1",
    )


def _build_result() -> TransformResult[NormalizedEmployeesRow]:
    row = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password="TopSecret123",
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id="RID-1",
    )
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="line:1", values={}),
        row=row,
        row_ref=None,
        match_key=None,
        secret_candidates={},
        errors=[],
        warnings=[],
    )


def test_enricher_writes_encrypted_secret_to_vault(tmp_path: Path):
    store, repository, locator, key_provider, cipher, engine = _build_store(tmp_path)
    try:
        enricher = _build_enricher(store)
        result = enricher.enrich(_build_result())

        assert result.meta.get("secret_fields") == ["password"]
        assert result.secret_candidates == {}
        assert result.row is not None
        assert result.row.password is None

        locator_hash = locator.build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": "Doe|John|M|100"},
        )
        secret_record = repository.get_secret(
            dataset="employees",
            field="password",
            locator_hash=locator_hash,
            locator_version="v1",
            run_id="run-1",
        )
        assert secret_record is not None
        assert secret_record.run_id == "run-1"
        assert secret_record.ciphertext != b"TopSecret123"

        dek_record = repository.get_active_dek()
        assert dek_record is not None
        master_key = key_provider.get_active_key()
        dek_plaintext = cipher.unwrap_dek(
            wrapped_dek=dek_record.wrapped_dek,
            master_key=master_key.key_material,
            wrap_algo=dek_record.wrap_algo,
        )
        restored = cipher.decrypt(
            ciphertext=secret_record.ciphertext,
            dek_plaintext=dek_plaintext,
            cipher_algo=secret_record.cipher_algo,
        )
        assert restored == "TopSecret123"
    finally:
        engine.close()
