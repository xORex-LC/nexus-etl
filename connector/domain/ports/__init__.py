"""Единый экспорт доменных портов."""

from connector.domain.ports.cache import (
    PendingLink,
    PendingRow,
)
from connector.domain.ports.target import RequestSpec, ExecutionResult, RequestExecutorProtocol, TargetPageResult, TargetPagedReaderProtocol
from connector.domain.ports.transform import RowSource, SourceMapper, DictionaryProviderPort
from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol

__all__ = [
    "PendingLink",
    "PendingRow",
    "RequestSpec",
    "ExecutionResult",
    "RequestExecutorProtocol",
    "TargetPageResult",
    "TargetPagedReaderProtocol",
    "RowSource",
    "SourceMapper",
    "DictionaryProviderPort",
    "SecretProviderProtocol",
    "SecretStoreProtocol",
]
