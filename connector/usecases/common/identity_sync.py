"""
Назначение:
    Общая post-write синхронизация identity-индекса и pending-записей.
"""

from __future__ import annotations

from typing import Any, Mapping

from connector.domain.ports.cache.roles import ApplyRuntimePort
from connector.domain.transform.matcher.identity_keys import format_identity_key


class IdentityIndexSyncer:
    """
    Назначение/ответственность:
        Синхронизирует identity-индекс после успешной записи в target/cache и
        закрывает pending-записи для совпавших identity-ключей.
    """

    def __init__(
        self,
        runtime: ApplyRuntimePort,
        identity_keys: dict[str, set[str]] | None = None,
        identity_id_fields: dict[str, str] | None = None,
    ) -> None:
        self.runtime = runtime
        self.identity_keys = identity_keys or {}
        self.identity_id_fields = identity_id_fields or {}

    def id_field_for(self, dataset: str) -> str:
        """Вернуть имя поля идентификатора для датасета (`_id` по умолчанию)."""
        return self.identity_id_fields.get(dataset, "_id")

    def sync(
        self,
        dataset: str,
        resolved_id: Any | None,
        key_values: Mapping[str, Any] | None,
    ) -> None:
        """
        Обновить identity-индекс и попытаться закрыть pending по найденным ключам.

        Инварианты:
            - запись выполняется только если для dataset объявлены identity_keys;
            - пустой/None resolved_id и пустые ключевые значения пропускаются;
            - side effect: upsert_identity + mark_resolved через runtime-порт.
        """
        key_names = self.identity_keys.get(dataset)
        if not key_names:
            return

        resolved_id_str = self._normalize_value(resolved_id)
        if resolved_id_str is None:
            return

        values = key_values or {}
        for key_name in key_names:
            value_str = self._normalize_value(values.get(key_name))
            if value_str is None:
                continue
            identity_key = format_identity_key(key_name, value_str)
            self.runtime.upsert_identity(dataset, identity_key, resolved_id_str)
            self._resolve_pending_for_key(dataset, identity_key)

    def _resolve_pending_for_key(self, dataset: str, identity_key: str) -> None:
        pending = self.runtime.list_pending_for_key(dataset, identity_key)
        for item in pending:
            self.runtime.mark_resolved(item.pending_id)

    @staticmethod
    def _normalize_value(value: Any | None) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        if value_str == "":
            return None
        return value_str


__all__ = ["IdentityIndexSyncer"]
