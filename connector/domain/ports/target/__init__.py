"""Порты взаимодействия с целевой системой (apply + execution + read)."""

from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.ports.target.execution import RequestSpec, ExecutionResult, RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPageResult, TargetPagedReaderProtocol

__all__ = [
    "ApplyAdapterProtocol",
    "RequestSpec",
    "ExecutionResult",
    "RequestExecutorProtocol",
    "TargetPageResult",
    "TargetPagedReaderProtocol",
]
