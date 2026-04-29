"""
Назначение:
    Доменный storage-контракт Vault для ciphertext и operational metadata.
"""

from __future__ import annotations

from typing import ContextManager, Protocol

from connector.domain.secrets.models import (
    VaultDekRecord,
    VaultProbeRecord,
    VaultSecretRecord,
    VaultUnsealMetadata,
)


class SecretVaultRepositoryPort(Protocol):
    """
    Назначение:
        Контракт операций хранения секретов, DEK и startup probe.

    Граница:
        Порт не раскрывает реализацию backend (SQLite, Postgres, внешний Vault).
    """

    def transaction(self) -> ContextManager[None]:
        """
        Контракт:
            Открыть атомарную транзакцию storage-операций.
        """
        ...

    def upsert_secret(self, record: VaultSecretRecord) -> None:
        """
        Контракт:
            Создать или обновить запись секрета в уникальном scope locator.
        """
        ...

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        locator_hash: str,
        locator_version: str,
        run_id: str | None,
    ) -> VaultSecretRecord | None:
        """
        Контракт:
            Вернуть секрет по locator scope с учётом run_id политики.
        """
        ...

    def delete_secret(
        self,
        *,
        dataset: str,
        field: str,
        locator_hash: str,
        locator_version: str,
        run_id: str | None,
    ) -> int:
        """
        Контракт:
            Удалить секрет по locator scope. Вернуть число удалённых записей.
        """
        ...

    def upsert_dek(self, record: VaultDekRecord) -> None:
        """
        Контракт:
            Создать или обновить wrapped DEK запись.
        """
        ...

    def get_dek(self, *, dek_version: str) -> VaultDekRecord | None:
        """
        Контракт:
            Вернуть DEK запись по версии.
        """
        ...

    def get_active_dek(self) -> VaultDekRecord | None:
        """
        Контракт:
            Вернуть активный DEK для write-path.
        """
        ...

    def list_deks(self) -> tuple[VaultDekRecord, ...]:
        """
        Контракт:
            Вернуть все DEK-записи, доступные для lifecycle-операций (rewrap/rotate).
        """
        ...

    def upsert_probe(self, record: VaultProbeRecord) -> None:
        """
        Контракт:
            Создать или обновить startup probe запись.
        """
        ...

    def get_probe(self, *, probe_name: str) -> VaultProbeRecord | None:
        """
        Контракт:
            Вернуть startup probe запись по имени.
        """
        ...

    def get_last_rotated_at(self) -> str | None:
        """
        Контракт:
            Вернуть timestamp последней успешной ротации ключа (ISO UTC) или None.
        """
        ...

    def set_last_rotated_at(self, iso_utc: str) -> None:
        """
        Контракт:
            Зафиксировать timestamp последней успешной ротации ключа (ISO UTC).
        """
        ...

    def set_last_rotation_result(self, *, result: str, reason: str | None = None) -> None:
        """
        Контракт:
            Зафиксировать результат последней lifecycle-операции ротации.
        """
        ...

    def get_last_rotation_result(self) -> str | None:
        """
        Контракт:
            Вернуть код результата последней lifecycle-операции (`rotating|ok|failed|...`) или None.
        """
        ...

    def get_last_rotation_reason(self) -> str | None:
        """
        Контракт:
            Вернуть служебную причину последней lifecycle-операции или None.
        """
        ...

    def get_last_rotation_run_id(self) -> str | None:
        """
        Контракт:
            Вернуть run_id последней lifecycle-операции или None.
        """
        ...

    def set_last_rotation_run_id(self, run_id: str | None) -> None:
        """
        Контракт:
            Зафиксировать run_id последней lifecycle-операции;
            при run_id=None удалить значение.
        """
        ...

    def get_unseal_metadata(self) -> VaultUnsealMetadata | None:
        """
        Контракт:
            Вернуть metadata unseal-модели или None, если vault ещё не инициализирован.
        """
        ...

    def upsert_unseal_metadata(self, metadata: VaultUnsealMetadata) -> None:
        """
        Контракт:
            Создать или заменить metadata unseal-модели.
        """
        ...
