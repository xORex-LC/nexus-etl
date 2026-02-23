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
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from connector.infra.dictionaries.loader_csv import DictionaryCsvLoadEvent


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


@dataclass
class _DictionaryRuntimeMetadata:
    """
    Назначение:
        Сериализуемая runtime metadata одного словаря для report snapshot.
    """

    row_count: int | None = None
    fingerprint_kind: str | None = None
    version_info: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = field(default_factory=list)


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
        self._runtime_enabled: bool | None = None
        self._load_strategy: str | None = None
        self._declared_dict_names: tuple[str, ...] = ()
        self._metadata_by_dict: dict[str, _DictionaryRuntimeMetadata] = {}
        self._anomalies: list[dict[str, Any]] = []

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

    def record_runtime_initialized(
        self,
        *,
        enabled: bool,
        load_strategy: str,
        declared_dict_names: tuple[str, ...],
    ) -> None:
        """
        Назначение:
            Зафиксировать runtime-state словарного слоя для report snapshot.

        Contract:
            - Вызывается orchestration/DI слоем при init backend resource.
            - Не инициирует загрузку словарей и не меняет counters.
        """
        self._runtime_enabled = enabled
        self._load_strategy = load_strategy
        self._declared_dict_names = tuple(sorted(declared_dict_names))
        for dict_name in self._declared_dict_names:
            self._touch_metadata(dict_name)

    def record_dictionary_loaded(self, event: DictionaryCsvLoadEvent) -> None:
        """
        Назначение:
            Зафиксировать успешную загрузку словаря (version metadata + empty-source warning path).
        """
        meta = self._touch_metadata(event.dict_name)
        meta.row_count = event.row_count
        meta.fingerprint_kind = event.version_info.fingerprint_kind
        meta.version_info = asdict(event.version_info)

        if event.source_empty:
            anomaly = {
                "code": "DICT_SOURCE_EMPTY",
                "severity": "WARNING",
                "dict_name": event.dict_name,
                "path": event.path,
                "row_count": event.row_count,
            }
            meta.anomalies.append(anomaly)
            self._anomalies.append(anomaly)
            self._logger.warning(
                "source_empty",
                component="dictionary",
                dict_name=event.dict_name,
                op="load",
                backend=self._backend,
                code="DICT_SOURCE_EMPTY",
                severity="WARNING",
                row_count=event.row_count,
                path=event.path,
                version_id=event.version_info.version_id,
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
        all_dict_names = sorted(set(self._per_dictionary.keys()) | set(self._metadata_by_dict.keys()))
        dictionaries_detail: dict[str, dict[str, Any]] = {}
        for dict_name in all_dict_names:
            counters = self._per_dictionary.get(dict_name, _LookupCounters())
            meta = self._metadata_by_dict.get(dict_name)
            dictionaries_detail[dict_name] = {
                **counters.as_dict(),
                "row_count": meta.row_count if meta is not None else None,
                "fingerprint_kind": meta.fingerprint_kind if meta is not None else None,
                "version_info": meta.version_info if meta is not None else None,
                "anomalies": list(meta.anomalies) if meta is not None else [],
            }

        loaded_count = sum(
            1
            for meta in self._metadata_by_dict.values()
            if meta.version_info is not None
        )
        return {
            "component": "dictionary",
            "backend": self._backend,
            "aggregate": self._aggregate.as_dict(),
            "summary": {
                "runtime_enabled": self._runtime_enabled,
                "load_strategy": self._load_strategy,
                "declared_dictionaries": list(self._declared_dict_names),
                "declared_count": len(self._declared_dict_names),
                "loaded_count": loaded_count,
                "warnings_count": len(self._anomalies),
            },
            "anomalies": list(self._anomalies),
            "dictionaries_detail": dictionaries_detail,
        }

    def _touch_counters(self, dict_name: str) -> _LookupCounters:
        counters = self._per_dictionary.get(dict_name)
        if counters is None:
            counters = _LookupCounters()
            self._per_dictionary[dict_name] = counters
        return counters

    def _touch_metadata(self, dict_name: str) -> _DictionaryRuntimeMetadata:
        meta = self._metadata_by_dict.get(dict_name)
        if meta is None:
            meta = _DictionaryRuntimeMetadata()
            self._metadata_by_dict[dict_name] = meta
        return meta

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
