"""Topology logging adapter для native structlog runtime.

Адаптирует transport-neutral `TopologyEventSink` к runtime logger-у. Topology
code не знает о backend напрямую, а CLI runtime передаёт ему structlog logger.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from connector.domain.ports.topology import TopologyEventSink


class StructlogTopologyEventSink(TopologyEventSink):
    """Писать topology-события в текущий command logger."""

    def __init__(self, *, logger: Any) -> None:
        self._logger = logger

    def enabled(self, level: int) -> bool:
        checker = getattr(self._logger, "is_enabled_for", None)
        if callable(checker):
            return bool(checker(level))
        checker = getattr(self._logger, "isEnabledFor", None)
        if callable(checker):
            return bool(checker(level))
        wrapped = getattr(self._logger, "_logger", None)
        if wrapped is not None and hasattr(wrapped, "isEnabledFor"):
            return bool(wrapped.isEnabledFor(level))
        return True

    def emit(
        self,
        *,
        level: int,
        event: str,
        payload: Mapping[str, Any],
    ) -> None:
        if not self.enabled(level):
            return
        _dispatch_log(self._logger, level, event, scope="topology", **payload)


def _dispatch_log(logger: Any, level: int, event: str, **fields: Any) -> None:
    if level >= logging.CRITICAL:
        logger.critical(event, **fields)
    elif level >= logging.ERROR:
        logger.error(event, **fields)
    elif level >= logging.WARNING:
        logger.warning(event, **fields)
    elif level >= logging.INFO:
        logger.info(event, **fields)
    else:
        logger.debug(event, **fields)


__all__ = ["StructlogTopologyEventSink"]
