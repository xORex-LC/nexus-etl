"""Порты взаимодействия с целевой системой (исполнение + чтение)."""

from connector.domain.ports.target.execution import RequestSpec, ExecutionResult, RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPageResult, TargetPagedReaderProtocol

__all__ = [
    "RequestSpec",
    "ExecutionResult",
    "RequestExecutorProtocol",
    "TargetPageResult",
    "TargetPagedReaderProtocol",
]
