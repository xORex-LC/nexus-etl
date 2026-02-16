"""Контракты target-core (совместимый слой для текущей реализации)."""

from __future__ import annotations

from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.execution import RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPagedReaderProtocol
from connector.infra.target.core.provider import TargetProvider
from connector.infra.target.core.runtime import TargetRuntime
from connector.infra.target.driver import TargetDriver

__all__ = [
    "RequestExecutorProtocol",
    "TargetPagedReaderProtocol",
    "TargetProvider",
    "TargetDriver",
    "TargetRuntime",
    "SecretProviderProtocol",
]
