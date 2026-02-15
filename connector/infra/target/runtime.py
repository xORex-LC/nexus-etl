"""
TargetRuntime — facade для взаимодействия delivery с target-системой.

Назначение:
    Единая точка доступа к инструментам target (executor, reader, check, meta, stats).
    Delivery работает только через TargetRuntime, не зная конкретную target-инфру.
"""

from __future__ import annotations

from typing import Protocol

from connector.domain.ports.target.execution import RequestExecutorProtocol
from connector.domain.ports.target.read import TargetPagedReaderProtocol
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetMeta,
    TargetStats,
)


class TargetRuntime(Protocol):
    """
    Протокол TargetRuntime — граница зависимости для delivery.

    Контракт:
        - executor: адаптер RequestExecutorProtocol для apply.
        - reader: адаптер TargetPagedReaderProtocol для cache refresh (может быть None).
        - check(): health-check target-системы.
        - meta(): типизированные метаданные target.
        - stats(): типизированная статистика.
        - reset(): сброс счётчиков.
    """

    @property
    def executor(self) -> RequestExecutorProtocol: ...

    @property
    def reader(self) -> TargetPagedReaderProtocol | None: ...

    def check(self) -> TargetCheckResult: ...

    def meta(self) -> TargetMeta: ...

    def stats(self) -> TargetStats: ...

    def reset(self) -> None: ...


class DefaultTargetRuntime:
    """
    Production-реализация TargetRuntime.

    Назначение:
        Facade над TargetGateway + TargetConnectionConfig.
        Gateway structurally satisfies RequestExecutorProtocol и TargetPagedReaderProtocol.
    """

    def __init__(
        self,
        *,
        gateway: TargetGateway,
        config: TargetConnectionConfig,
        has_reader: bool = True,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._has_reader = has_reader

    @property
    def executor(self) -> RequestExecutorProtocol:
        return self._gateway  # type: ignore[return-value]

    @property
    def reader(self) -> TargetPagedReaderProtocol | None:
        return self._gateway if self._has_reader else None  # type: ignore[return-value]

    def check(self) -> TargetCheckResult:
        return self._gateway.health_check()

    def meta(self) -> TargetMeta:
        return TargetMeta(
            target_type=self._config.target_type,
            base_url=self._config.base_url,
            transport=self._config.transport,
        )

    def stats(self) -> TargetStats:
        req, ret, fail = self._gateway.get_stats()
        return TargetStats(
            requests_total=req,
            retries_total=ret,
            failures_total=fail,
        )

    def reset(self) -> None:
        self._gateway.reset_stats()
