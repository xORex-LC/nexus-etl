"""
Назначение:
    Telemetry/structured logging для Dictionary runtime v1.

Граница ответственности:
    - Ведет counters по lookup-операциям (aggregate + per-dictionary).
    - Логирует события словарного runtime через `structlog` без plaintext ключей.
    - Готовит snapshot payload для последующего flush в report context.
    - Не знает о DI/container wiring и не зависит от delivery/report collector.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import structlog


@dataclass
class _LookupCounters:
    """
    Назначение:
        Накопители counters для aggregate/per-dictionary статистики.
    """

    lookup_total: int = 0
    lookup_hit: int = 0
    lookup_miss: int = 0
    lookup_error: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "lookup_total": self.lookup_total,
            "lookup_hit": self.lookup_hit,
            "lookup_miss": self.lookup_miss,
            "lookup_error": self.lookup_error,
        }


class DictionaryTelemetry:
    """
    Назначение:
        Когезивный v1 telemetry-объект (counters + structlog logging).

    Контракт:
        - На вход для логов принимает только `key_fingerprint`, а не plaintext key.
        - Sampling debug-логов детерминированный (по event+dict_name+fingerprint).
        - Snapshot предназначен для передачи в `report.context["dictionary"]` на delivery-уровне.
    """

    def __init__(
        self,
        *,
        fingerprint_salt: str,
        fingerprint_prefix_len: int = 12,
        backend: str = "polars",
        lookup_hit_sample_percent: int = 1,
        lookup_miss_sample_percent: int = 10,
    ) -> None:
        self._fingerprint_salt = fingerprint_salt
        self._fingerprint_prefix_len = fingerprint_prefix_len
        self._backend = backend
        self._lookup_hit_sample_percent = self._validate_percent(
            "lookup_hit_sample_percent",
            lookup_hit_sample_percent,
        )
        self._lookup_miss_sample_percent = self._validate_percent(
            "lookup_miss_sample_percent",
            lookup_miss_sample_percent,
        )
        self._logger = structlog.get_logger(__name__)
        self._aggregate = _LookupCounters()
        self._per_dictionary: dict[str, _LookupCounters] = {}

    def build_key_fingerprint(self, normalized_key: Any) -> str:
        """
        Назначение:
            Построить безопасный fingerprint ключа для логов/telemetry.

        Contract:
            - Использует `sha256(salt + normalized_key_text)`.
            - Возвращает только короткий hex-prefix.
            - Salt нигде не логируется и не возвращается наружу.
        """
        value_text = "" if normalized_key is None else str(normalized_key)
        payload = (self._fingerprint_salt + value_text).encode("utf-8", errors="replace")
        digest = hashlib.sha256(payload).hexdigest()
        return digest[: self._fingerprint_prefix_len]

    def record_lookup_result(
        self,
        *,
        dict_name: str,
        op: str,
        hit: bool,
        key_fingerprint: str,
        result_count: int,
        limit: int | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> None:
        """
        Назначение:
            Обновить counters и (по sampling) записать debug-событие для успешной операции.
        """
        counters = self._touch_counters(dict_name)
        self._increment(counters, "lookup_total")
        self._increment(counters, "lookup_hit" if hit else "lookup_miss")

        event = "lookup_hit" if hit else "lookup_miss"
        if self._should_sample_debug(event=event, dict_name=dict_name, key_fingerprint=key_fingerprint):
            self._logger.debug(
                event,
                component="dictionary",
                dict_name=dict_name,
                op=op,
                backend=self._backend,
                key_fingerprint=key_fingerprint,
                result_count=result_count,
                limit=limit,
                fields=list(fields) if fields is not None else None,
            )

    def record_lookup_error(
        self,
        *,
        dict_name: str,
        op: str,
        key_fingerprint: str,
        error: Exception,
    ) -> None:
        """
        Назначение:
            Обновить counters и записать warning/error-событие lookup failure.
        """
        counters = self._touch_counters(dict_name)
        self._increment(counters, "lookup_total")
        self._increment(counters, "lookup_error")

        error_code = getattr(error, "code", None)
        self._logger.warning(
            "lookup_error",
            component="dictionary",
            dict_name=dict_name,
            op=op,
            backend=self._backend,
            key_fingerprint=key_fingerprint,
            error_type=type(error).__name__,
            error_code=error_code,
        )

    def snapshot(self) -> dict[str, Any]:
        """
        Назначение:
            Вернуть сериализуемый snapshot counters для report context.
        """
        dictionaries_detail = {
            dict_name: counters.as_dict()
            for dict_name, counters in sorted(self._per_dictionary.items())
        }
        return {
            "component": "dictionary",
            "backend": self._backend,
            "aggregate": self._aggregate.as_dict(),
            "dictionaries_detail": dictionaries_detail,
        }

    def _touch_counters(self, dict_name: str) -> _LookupCounters:
        counters = self._per_dictionary.get(dict_name)
        if counters is None:
            counters = _LookupCounters()
            self._per_dictionary[dict_name] = counters
        return counters

    def _increment(self, dict_counters: _LookupCounters, key: str) -> None:
        setattr(self._aggregate, key, getattr(self._aggregate, key) + 1)
        setattr(dict_counters, key, getattr(dict_counters, key) + 1)

    def _should_sample_debug(self, *, event: str, dict_name: str, key_fingerprint: str) -> bool:
        percent = self._sample_percent_for_event(event)
        if percent <= 0:
            return False
        bucket = self._sample_bucket(event=event, dict_name=dict_name, key_fingerprint=key_fingerprint)
        return bucket < percent

    def _sample_bucket(self, *, event: str, dict_name: str, key_fingerprint: str) -> int:
        payload = f"{event}|{dict_name}|{key_fingerprint}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        return int.from_bytes(digest[:4], byteorder="big") % 100

    def _sample_percent_for_event(self, event: str) -> int:
        if event == "lookup_hit":
            return self._lookup_hit_sample_percent
        if event == "lookup_miss":
            return self._lookup_miss_sample_percent
        return 0

    @staticmethod
    def _validate_percent(name: str, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be within [0, 100]")
        return value


__all__ = ["DictionaryTelemetry"]
