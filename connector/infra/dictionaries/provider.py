"""
Назначение:
    Adapter `DictionaryProviderPort` поверх `PolarsDictionaryBackend`.

Граница ответственности:
    - Делегирует lookup/contains/canonicalize в backend.
    - Обновляет dictionary telemetry (counters + structured logs).
    - Не выполняет DI wiring и не знает о delivery/report flush.
"""

from __future__ import annotations

from typing import Any

from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.telemetry import DictionaryTelemetry


class PolarsDictionaryProvider(DictionaryProviderPort):
    """
    Назначение:
        Runtime adapter для доменного `DictionaryProviderPort` поверх Polars backend.

    Контракт:
        - Телеметрия остается отдельным infra-объектом (`DictionaryTelemetry`).
        - Порт не расширяется методами метрик/репорта.
    """

    def __init__(
        self,
        *,
        backend: PolarsDictionaryBackend,
        telemetry: DictionaryTelemetry,
    ) -> None:
        self._backend = backend
        self._telemetry = telemetry

    def lookup(
        self,
        dict_name: str,
        key: str,
        at: Any | None = None,
        fields: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Назначение:
            Lookup через backend с telemetry hit/miss/error.
        """
        key_fingerprint = self._safe_key_fingerprint(dict_name=dict_name, value=key)
        try:
            rows = self._backend.lookup(dict_name, key, at=at, fields=fields, limit=limit)
        except Exception as exc:
            self._telemetry.record_lookup_error(
                dict_name=dict_name,
                op="lookup",
                key_fingerprint=key_fingerprint,
                error=exc,
            )
            raise

        self._telemetry.record_lookup_result(
            dict_name=dict_name,
            op="lookup",
            hit=bool(rows),
            key_fingerprint=key_fingerprint,
            result_count=len(rows),
            limit=limit,
            fields=fields,
        )
        return rows

    def contains(self, dict_name: str, value: str, at: Any | None = None) -> bool:
        """
        Назначение:
            Membership-check через backend с telemetry (как lookup family op).
        """
        key_fingerprint = self._safe_key_fingerprint(dict_name=dict_name, value=value)
        try:
            is_present = self._backend.contains(dict_name, value, at=at)
        except Exception as exc:
            self._telemetry.record_lookup_error(
                dict_name=dict_name,
                op="contains",
                key_fingerprint=key_fingerprint,
                error=exc,
            )
            raise

        self._telemetry.record_lookup_result(
            dict_name=dict_name,
            op="contains",
            hit=is_present,
            key_fingerprint=key_fingerprint,
            result_count=1 if is_present else 0,
            limit=None,
            fields=None,
        )
        return is_present

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        at: Any | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Назначение:
            Канонизация через backend с telemetry (как lookup family op).
        """
        key_fingerprint = self._safe_key_fingerprint(dict_name=dict_name, value=value)
        try:
            rows = self._backend.canonicalize(dict_name, value, at=at, limit=limit)
        except Exception as exc:
            self._telemetry.record_lookup_error(
                dict_name=dict_name,
                op="canonicalize",
                key_fingerprint=key_fingerprint,
                error=exc,
            )
            raise

        self._telemetry.record_lookup_result(
            dict_name=dict_name,
            op="canonicalize",
            hit=bool(rows),
            key_fingerprint=key_fingerprint,
            result_count=len(rows),
            limit=limit,
            fields=None,
        )
        return rows

    def _safe_key_fingerprint(self, *, dict_name: str, value: Any) -> str:
        """
        Назначение:
            Получить fingerprint по нормализованному ключу без влияния на основной path.

        Contract:
            - Ошибки нормализации/резолва spec не ломают основную операцию.
            - В telemetry всегда уходит fingerprint, но не plaintext ключ.
        """
        normalized_value = value
        try:
            compiled = self._backend.bundle.get(dict_name)
            normalized_value = compiled.normalize_key(value)
        except Exception:
            # Не подменяем business/runtime errors ошибкой telemetry normalization.
            normalized_value = value
        return self._telemetry.build_key_fingerprint(normalized_value)


__all__ = ["PolarsDictionaryProvider"]
