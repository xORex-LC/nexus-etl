"""
Назначение:
    Read-path сервис Vault: `load ciphertext -> unwrap DEK -> decrypt -> hydrate payload`.

Граница ответственности:
    - реализует внешний `SecretProviderProtocol` для apply-контура;
    - не знает о конкретном backend-хранилище (SQLite/Postgres/KMS);
    - возвращает `None` только для "секрет не найден/контекст отсутствует";
    - ошибки чтения/дешифрования/целостности поднимает как доменные `Secret*Error`.
"""

from __future__ import annotations

from typing import Any

from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.locator import SecretLocatorPort
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import (
    SecretDecryptionError,
    SecretIntegrityError,
    SecretKeyConfigError,
    SecretReadError,
)
from connector.domain.secrets.models import VaultDekRecord

DEFAULT_LOCATOR_VERSION = "v1"


class SecretVaultReadService(SecretProviderProtocol):
    """
    Назначение:
        Orchestration-слой чтения секрета из vault по `dataset/field/source_ref`.

    Инварианты:
        - locator строится тем же правилом, что и в write-path;
        - run-scope поддерживает precedence `exact run_id -> global (NULL)`;
        - secret payload никогда не логируется и не возвращается частично.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        key_provider: VaultKeyProviderPort,
        locator: SecretLocatorPort,
        locator_version: str = DEFAULT_LOCATOR_VERSION,
        default_run_id: str | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._key_provider = key_provider
        self._locator = locator
        self._locator_version = locator_version
        self._default_run_id = default_run_id

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        row_id: str | None = None,
        line_no: int | None = None,
        source_ref: dict | None = None,
        target_id: str | None = None,
        run_id: str | None = None,
    ) -> str | None:
        """
        Назначение:
            Вернуть plaintext секрета для apply-гидрации.

        Контракт:
            - если входного locator-контекста недостаточно, возвращает `None`;
            - если запись отсутствует, возвращает `None`;
            - storage/decrypt/integrity ошибки выбрасываются как `Secret*Error`.

        Алгоритм:
            1. Проверить `source_ref.match_key`; без него чтение не выполняется.
            2. Построить `locator_hash` тем же versioned-правилом, что write-path.
            3. Прочитать secret record с run-scope fallback.
            4. Прочитать DEK, попытаться unwrap через candidate keyring.
            5. Расшифровать ciphertext и вернуть plaintext.
        """
        _ = (row_id, line_no, target_id)  # Контекст трассировки сохраняется на boundary-уровне.

        normalized_source_ref = _normalize_source_ref(source_ref)
        if normalized_source_ref is None:
            return None

        effective_run_id = run_id if run_id is not None else self._default_run_id
        match_key = normalized_source_ref["match_key"]

        try:
            locator_hash = self._locator.build_locator_hash(
                dataset=dataset,
                field=field,
                source_ref=normalized_source_ref,
                locator_version=self._locator_version,
            )
            record = self._repository.get_secret(
                dataset=dataset,
                field=field,
                match_key=match_key,
                locator_hash=locator_hash,
                locator_version=self._locator_version,
                run_id=effective_run_id,
            )
            if record is None:
                return None

            dek_record = self._repository.get_dek(dek_version=record.dek_version)
            if dek_record is None:
                raise SecretReadError(
                    "Failed to read secret from vault",
                    details={
                        "reason": "dek_not_found",
                        "dek_version": record.dek_version,
                        "locator_version": record.locator_version,
                    },
                )

            dek_plaintext = self._unwrap_dek(dek_record)
            return self._cipher.decrypt(
                ciphertext=record.ciphertext,
                dek_plaintext=dek_plaintext,
                cipher_algo=record.cipher_algo,
            )
        except (SecretReadError, SecretDecryptionError, SecretIntegrityError):
            raise
        except SecretKeyConfigError as exc:
            raise SecretReadError(
                "Failed to read secret from vault",
                details={"reason": "key_config_error"},
            ) from exc
        except ValueError as exc:
            raise SecretReadError(
                "Failed to read secret from vault",
                details={"reason": "locator_error", "locator_version": self._locator_version},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise SecretReadError(
                "Failed to read secret from vault",
                details={"reason": "unexpected_error"},
            ) from exc

    def _unwrap_dek(self, record: VaultDekRecord) -> bytes:
        """
        Назначение:
            Раскрыть DEK через keyring с приоритетом ключа из metadata.

        Алгоритм:
            1. Поставить `wrap_key_version` первым кандидатом.
            2. Добавить остальные ключи как fallback.
            3. На первом успешном unwrap вернуть DEK.
            4. Если все кандидаты не подошли — вернуть `SecretDecryptionError`.
        """
        for key in self._candidate_master_keys(record.wrap_key_version):
            try:
                return self._cipher.unwrap_dek(
                    wrapped_dek=record.wrapped_dek,
                    master_key=key.key_material,
                    wrap_algo=record.wrap_algo,
                )
            except (SecretDecryptionError, SecretIntegrityError):
                continue

        raise SecretDecryptionError(
            "Failed to decrypt secret",
            details={
                "reason": "dek_unwrap_failed",
                "dek_version": record.dek_version,
                "key_version": record.wrap_key_version,
            },
        )

    def _candidate_master_keys(self, wrap_key_version: str) -> list[VaultMasterKey]:
        """
        Назначение:
            Сформировать ordered keyring для unwrap.
        """
        candidates: list[VaultMasterKey] = []
        hinted = self._key_provider.find_key(wrap_key_version)
        if hinted is not None:
            candidates.append(hinted)

        for key in self._key_provider.get_all_keys():
            if hinted is not None and key.key_version == hinted.key_version:
                continue
            candidates.append(key)
        return candidates


def _normalize_source_ref(source_ref: dict[str, Any] | None) -> dict[str, str] | None:
    """
    Назначение:
        Нормализовать минимум locator-контекста, необходимого для read-path.

    Контракт:
        Требуется только `match_key`; пустые/невалидные значения считаются отсутствием контекста.
    """
    if not isinstance(source_ref, dict):
        return None
    raw_match_key = source_ref.get("match_key")
    if not isinstance(raw_match_key, str):
        return None
    normalized = raw_match_key.strip()
    if not normalized:
        return None
    return {"match_key": normalized}
