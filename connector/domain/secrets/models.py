"""
Назначение:
    Доменные модели Vault-подсистемы (ciphertext + operational metadata).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VaultSecretRecord:
    """
    Назначение:
        Хранимая запись секрета в vault storage.

    Инварианты:
        - ciphertext остаётся непрозрачным для бизнес-логики;
        - metadata не должна содержать plaintext секрета.
    """

    dataset: str
    field: str
    match_key: str | None
    locator_hash: str
    locator_version: str
    ciphertext: bytes | str
    cipher_algo: str
    key_version: str
    dek_version: str
    run_id: str | None
    created_at: str
    updated_at: str
    secret_id: int | None = None


@dataclass(frozen=True)
class VaultDekRecord:
    """
    Назначение:
        Запись wrapped DEK с lifecycle metadata.

    Инварианты:
        - wrapped_dek не содержит plaintext DEK;
        - активный DEK в write-path должен быть ровно один.
    """

    dek_version: str
    wrapped_dek: bytes | str
    wrap_algo: str
    wrap_key_version: str
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class VaultProbeRecord:
    """
    Назначение:
        Служебная запись для startup guard проверки ключей и целостности.
    """

    probe_name: str
    ciphertext: bytes | str
    cipher_algo: str
    key_version: str
    dek_version: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class VaultUnsealMetadata:
    """
    Назначение:
        Persistent metadata для восстановления master wrapping key из unseal passphrase.

    Инварианты:
        - Не содержит plaintext passphrase или master key material.
        - `kdf_salt` и `hmac_salt` независимы.
        - `hmac_digest` используется только для fail-fast проверки passphrase.
    """

    key_version: str
    kdf_algo: str
    kdf_salt: bytes | str
    kdf_time_cost: int
    kdf_memory_cost_kib: int
    kdf_parallelism: int
    kdf_hash_len: int
    hmac_algo: str
    hmac_salt: bytes | str
    hmac_digest: bytes | str
    created_at: str
    updated_at: str
