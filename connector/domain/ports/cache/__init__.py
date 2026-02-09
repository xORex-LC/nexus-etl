"""Порты доступа к кэшу."""

from connector.domain.ports.cache.gateway import CacheGatewayPort
from connector.domain.ports.cache.pending_links import PendingLink, PendingRow

__all__ = [
    "CacheGatewayPort",
    "PendingLink",
    "PendingRow",
]
