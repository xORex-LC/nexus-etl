"""
Назначение:
    Fernet-реализация SecretCipherPort для envelope encryption.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken

from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.secrets.errors import SecretDecryptionError, SecretIntegrityError, SecretKeyConfigError

FERNET_V1 = "FERNET_V1"


class FernetEnvelopeCipher(SecretCipherPort):
    """
    Назначение:
        Выполнить encrypt/decrypt секрета и wrap/unwrap DEK через Fernet.
    """

    def encrypt(
        self,
        *,
        plaintext: str,
        dek_plaintext: bytes,
        cipher_algo: str,
    ) -> bytes | str:
        _ensure_algo(cipher_algo, expected=FERNET_V1, algo_kind="cipher")
        fernet = _build_fernet_from_dek(dek_plaintext)
        try:
            return fernet.encrypt(plaintext.encode("utf-8"))
        except Exception as exc:
            raise SecretIntegrityError(
                "Failed to encrypt secret payload",
                details={"reason": "encrypt_failed", "cipher_algo": cipher_algo},
            ) from exc

    def decrypt(
        self,
        *,
        ciphertext: bytes | str,
        dek_plaintext: bytes,
        cipher_algo: str,
    ) -> str:
        _ensure_algo(cipher_algo, expected=FERNET_V1, algo_kind="cipher")
        token = _normalize_token(ciphertext, context="ciphertext")
        _validate_token_shape(token, context="ciphertext")
        fernet = _build_fernet_from_dek(dek_plaintext)
        try:
            plaintext = fernet.decrypt(token)
        except InvalidToken as exc:
            raise SecretDecryptionError(
                "Failed to decrypt secret payload",
                details={"reason": "invalid_token", "cipher_algo": cipher_algo},
            ) from exc
        except Exception as exc:
            raise SecretIntegrityError(
                "Secret payload integrity check failed",
                details={"reason": "decrypt_failed", "cipher_algo": cipher_algo},
            ) from exc
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretIntegrityError(
                "Secret payload has invalid utf-8 encoding",
                details={"reason": "invalid_utf8"},
            ) from exc

    def wrap_dek(
        self,
        *,
        dek_plaintext: bytes,
        master_key: str,
        wrap_algo: str,
    ) -> bytes | str:
        _ensure_algo(wrap_algo, expected=FERNET_V1, algo_kind="wrap")
        fernet = _build_fernet_from_master_key(master_key)
        try:
            return fernet.encrypt(dek_plaintext)
        except Exception as exc:
            raise SecretIntegrityError(
                "Failed to wrap DEK",
                details={"reason": "wrap_failed", "wrap_algo": wrap_algo},
            ) from exc

    def unwrap_dek(
        self,
        *,
        wrapped_dek: bytes | str,
        master_key: str,
        wrap_algo: str,
    ) -> bytes:
        _ensure_algo(wrap_algo, expected=FERNET_V1, algo_kind="wrap")
        token = _normalize_token(wrapped_dek, context="wrapped_dek")
        _validate_token_shape(token, context="wrapped_dek")
        fernet = _build_fernet_from_master_key(master_key)
        try:
            return fernet.decrypt(token)
        except InvalidToken as exc:
            raise SecretDecryptionError(
                "Failed to unwrap DEK",
                details={"reason": "invalid_token", "wrap_algo": wrap_algo},
            ) from exc
        except Exception as exc:
            raise SecretIntegrityError(
                "Wrapped DEK integrity check failed",
                details={"reason": "unwrap_failed", "wrap_algo": wrap_algo},
            ) from exc


def _ensure_algo(algo: str, *, expected: str, algo_kind: str) -> None:
    if algo != expected:
        raise SecretIntegrityError(
            "Unsupported vault algorithm",
            details={"reason": "unsupported_algorithm", "algo_kind": algo_kind, "algo": algo, "expected": expected},
        )


def _build_fernet_from_dek(dek_plaintext: bytes) -> Fernet:
    try:
        return Fernet(dek_plaintext)
    except Exception as exc:
        raise SecretIntegrityError(
            "Invalid DEK format",
            details={"reason": "invalid_dek"},
        ) from exc


def _build_fernet_from_master_key(master_key: str) -> Fernet:
    try:
        return Fernet(master_key.encode("utf-8"))
    except Exception as exc:
        raise SecretKeyConfigError(
            "Invalid master key format",
            details={"reason": "invalid_master_key"},
        ) from exc


def _normalize_token(token: bytes | str, *, context: str) -> bytes:
    if isinstance(token, bytes):
        if not token:
            raise SecretIntegrityError(
                "Ciphertext token is empty",
                details={"reason": "empty_token", "context": context},
            )
        return token
    if isinstance(token, str):
        raw = token.encode("utf-8")
        if not raw:
            raise SecretIntegrityError(
                "Ciphertext token is empty",
                details={"reason": "empty_token", "context": context},
            )
        return raw
    raise SecretIntegrityError(
        "Ciphertext token has invalid type",
        details={"reason": "invalid_token_type", "context": context},
    )


def _validate_token_shape(token: bytes, *, context: str) -> None:
    # Быстрая проверка формата до decrypt: токен должен быть валидным urlsafe base64 и содержать Fernet version byte.
    try:
        decoded = base64.urlsafe_b64decode(token + b"=" * (-len(token) % 4))
    except Exception as exc:
        raise SecretIntegrityError(
            "Ciphertext token has invalid base64 format",
            details={"reason": "invalid_base64", "context": context},
        ) from exc
    if len(decoded) < 9 or decoded[0] != 0x80:
        raise SecretIntegrityError(
            "Ciphertext token has invalid Fernet envelope",
            details={"reason": "invalid_fernet_envelope", "context": context},
        )

