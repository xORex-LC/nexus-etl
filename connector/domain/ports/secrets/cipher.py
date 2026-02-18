"""
Назначение:
    Доменный crypto-контракт Vault-подсистемы.

Граница ответственности:
    Порт определяет операции шифрования/дешифрования секрета и обёртки DEK,
    но не задаёт конкретную криптобиблиотеку и формат хранения.
"""

from __future__ import annotations

from typing import Protocol


class SecretCipherPort(Protocol):
    """
    Назначение:
        Контракт криптографических операций для envelope encryption.

    Инварианты:
        - plaintext и key material не должны попадать в логи/исключения адаптера;
        - ошибка целостности и ошибка дешифрования должны различаться
          на уровне доменных исключений.
    """

    def encrypt(
        self,
        *,
        plaintext: str,
        dek_plaintext: bytes,
        cipher_algo: str,
    ) -> bytes | str:
        """
        Контракт:
            Зашифровать plaintext секрета с помощью переданного DEK.
        """
        ...

    def decrypt(
        self,
        *,
        ciphertext: bytes | str,
        dek_plaintext: bytes,
        cipher_algo: str,
    ) -> str:
        """
        Контракт:
            Расшифровать ciphertext секрета с помощью переданного DEK.
        """
        ...

    def wrap_dek(
        self,
        *,
        dek_plaintext: bytes,
        master_key: str,
        wrap_algo: str,
    ) -> bytes | str:
        """
        Контракт:
            Зашифровать DEK мастер-ключом для хранения в vault_dek.
        """
        ...

    def unwrap_dek(
        self,
        *,
        wrapped_dek: bytes | str,
        master_key: str,
        wrap_algo: str,
    ) -> bytes:
        """
        Контракт:
            Расшифровать wrapped DEK мастер-ключом.
        """
        ...

