"""Порты доступа к кэшу (репозиторий + идентичности + pending)."""

from connector.domain.ports.cache.repository import CacheRepositoryProtocol
from connector.domain.ports.cache.identity import IdentityRepository
from connector.domain.ports.cache.pending_links import PendingLinksRepository, PendingLink

__all__ = [
    "CacheRepositoryProtocol",
    "IdentityRepository",
    "PendingLinksRepository",
    "PendingLink",
]
