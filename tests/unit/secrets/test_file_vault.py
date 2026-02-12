from __future__ import annotations

from pathlib import Path

from connector.infra.secrets.file_vault_provider import FileVaultSecretProvider, FileVaultSecretStore


def test_file_vault_roundtrip_by_match_key(tmp_path: Path):
    vault_path = tmp_path / "vault.csv"
    store = FileVaultSecretStore(str(vault_path))
    provider = FileVaultSecretProvider(str(vault_path))

    store.put_many(dataset="employees", match_key="A|B|C|1", secrets={"password": "secret123"}, run_id="r1")

    value = provider.get_secret(
        dataset="employees",
        field="password",
        source_ref={"match_key": "A|B|C|1"},
        run_id="r1",
    )
    assert value == "secret123"


def test_file_vault_last_write_wins(tmp_path: Path):
    vault_path = tmp_path / "vault.csv"
    store = FileVaultSecretStore(str(vault_path))
    provider = FileVaultSecretProvider(str(vault_path))

    store.put_many(dataset="employees", match_key="A|B|C|1", secrets={"password": "first"}, run_id="r1")
    store.put_many(dataset="employees", match_key="A|B|C|1", secrets={"password": "second"}, run_id="r2")

    value = provider.get_secret(
        dataset="employees",
        field="password",
        source_ref={"match_key": "A|B|C|1"},
    )
    assert value == "second"
