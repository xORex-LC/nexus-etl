"""
SQLite cache table handlers.
"""

from connector.infra.cache.backends.sqlite.handlers.base import CacheDatasetHandler
from connector.infra.cache.backends.sqlite.handlers.generic_handler import GenericCacheHandler

__all__ = [
    "CacheDatasetHandler",
    "GenericCacheHandler",
]

