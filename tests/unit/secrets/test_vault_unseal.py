from __future__ import annotations

import pytest

from connector.domain.secrets.errors import SecretKeyConfigError
from connector.infra.secrets.unseal import UnsealedVaultKeyProvider, VaultUnsealService


class _Repo:
    def __init__(self, metadata=None) -> None:
        self._metadata = metadata

    def get_unseal_metadata(self):
        return self._metadata


def test_argon2id_unseal_derivation_is_deterministic_for_same_metadata() -> None:
    service = VaultUnsealService()
    metadata, first = service.create_metadata(
        passphrase="correct horse battery",
        key_version="mk_2026",
        now_utc="2026-04-28T00:00:00+00:00",
    )

    second = service.derive_key(passphrase="correct horse battery", metadata=metadata)

    assert second.key_version == first.key_version
    assert second.key_material == first.key_material


def test_wrong_unseal_passphrase_fails_hmac_check() -> None:
    service = VaultUnsealService()
    metadata, _ = service.create_metadata(
        passphrase="correct horse battery",
        key_version="mk_2026",
        now_utc="2026-04-28T00:00:00+00:00",
    )

    with pytest.raises(SecretKeyConfigError) as exc_info:
        service.derive_key(passphrase="wrong passphrase", metadata=metadata)

    assert exc_info.value.details["reason"] == "unseal_passphrase_invalid"


def test_unsealed_key_provider_returns_single_active_key() -> None:
    service = VaultUnsealService()
    metadata, expected = service.create_metadata(
        passphrase="correct horse battery",
        key_version="mk_2026",
        now_utc="2026-04-28T00:00:00+00:00",
    )
    provider = UnsealedVaultKeyProvider(
        repository=_Repo(metadata),
        unseal_service=service,
        passphrase="correct horse battery",
    )

    active = provider.get_active_key()

    assert active == expected
    assert provider.get_all_keys() == (expected,)
    assert provider.find_key("missing") is None
