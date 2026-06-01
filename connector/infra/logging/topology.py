"""Legacy topology logging adapter — bridge в текущую stdlib logging модель.

Адаптирует transport-neutral `TopologyEventSink` к существующему runtime logger-у,
используя `comp=topology` и logfmt-подобное сообщение. Это переходный слой:
topology code не знает о backend напрямую, а текущая CLI runtime точка получает
совместимый sink без ранней миграции всего приложения.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from connector.domain.ports.topology import TopologyEventSink
from connector.infra.logging.setup import log_event


class LegacyLogEventSink(TopologyEventSink):
    """Писать topology-события в текущий command logger."""

    def __init__(self, *, logger: logging.Logger, run_id: str) -> None:
        self._logger = logger
        self._run_id = run_id

    def enabled(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)

    def emit(
        self,
        *,
        level: int,
        event: str,
        payload: Mapping[str, Any],
    ) -> None:
        if not self.enabled(level):
            return
        message = _format_topology_event(event=event, payload=payload)
        log_event(self._logger, level, self._run_id, "topology", message)


def _format_topology_event(*, event: str, payload: Mapping[str, Any]) -> str:
    parts = [f"event={event}"]
    for key in sorted(payload):
        parts.append(f"{key}={_format_logfmt_value(payload[key])}")
    return " ".join(parts)


def _format_logfmt_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if value == "":
            return '""'
        if any(char.isspace() for char in value) or "=" in value:
            return json.dumps(value, ensure_ascii=False)
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

