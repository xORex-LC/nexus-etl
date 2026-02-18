from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from connector.domain.secrets.errors import SecretDecryptionError, SecretIntegrityError, SecretKeyConfigError
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher


def test_encrypt_decrypt_roundtrip():
    cipher = FernetEnvelopeCipher()
    dek = Fernet.generate_key()

    ciphertext = cipher.encrypt(
        plaintext="secret123",
        dek_plaintext=dek,
        cipher_algo=FERNET_V1,
    )
    restored = cipher.decrypt(
        ciphertext=ciphertext,
        dek_plaintext=dek,
        cipher_algo=FERNET_V1,
    )

    assert restored == "secret123"


def test_wrap_unwrap_dek_roundtrip():
    cipher = FernetEnvelopeCipher()
    master_key = Fernet.generate_key().decode("utf-8")
    dek_payload = b"generated-dek-value"

    wrapped = cipher.wrap_dek(
        dek_plaintext=dek_payload,
        master_key=master_key,
        wrap_algo=FERNET_V1,
    )
    unwrapped = cipher.unwrap_dek(
        wrapped_dek=wrapped,
        master_key=master_key,
        wrap_algo=FERNET_V1,
    )

    assert unwrapped == dek_payload


def test_decrypt_with_wrong_key_raises_secret_decryption_error():
    cipher = FernetEnvelopeCipher()
    dek = Fernet.generate_key()
    wrong_dek = Fernet.generate_key()
    ciphertext = cipher.encrypt(
        plaintext="payload",
        dek_plaintext=dek,
        cipher_algo=FERNET_V1,
    )

    with pytest.raises(SecretDecryptionError) as exc_info:
        cipher.decrypt(
            ciphertext=ciphertext,
            dek_plaintext=wrong_dek,
            cipher_algo=FERNET_V1,
        )

    assert exc_info.value.code == "SECRET_DECRYPTION_ERROR"


def test_decrypt_with_malformed_ciphertext_raises_integrity_error():
    cipher = FernetEnvelopeCipher()
    dek = Fernet.generate_key()

    with pytest.raises(SecretIntegrityError) as exc_info:
        cipher.decrypt(
            ciphertext=b"not-base64-token",
            dek_plaintext=dek,
            cipher_algo=FERNET_V1,
        )

    assert exc_info.value.code == "SECRET_INTEGRITY_ERROR"
    assert exc_info.value.details["reason"] in {"invalid_base64", "invalid_fernet_envelope"}


def test_encrypt_with_unsupported_algo_raises_integrity_error():
    cipher = FernetEnvelopeCipher()
    dek = Fernet.generate_key()

    with pytest.raises(SecretIntegrityError) as exc_info:
        cipher.encrypt(
            plaintext="payload",
            dek_plaintext=dek,
            cipher_algo="UNKNOWN",
        )

    assert exc_info.value.code == "SECRET_INTEGRITY_ERROR"
    assert exc_info.value.details["reason"] == "unsupported_algorithm"


def test_wrap_dek_with_invalid_master_key_raises_config_error():
    cipher = FernetEnvelopeCipher()

    with pytest.raises(SecretKeyConfigError) as exc_info:
        cipher.wrap_dek(
            dek_plaintext=b"payload",
            master_key="invalid-master-key",
            wrap_algo=FERNET_V1,
        )

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "invalid_master_key"

