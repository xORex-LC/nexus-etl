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
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetMeta,
    TargetStats,
)


class TargetRuntime(Protocol):
    """
    Протокол TargetRuntime — граница зависимости для delivery.

    Контракт:
        - executor: адаптер RequestExecutorProtocol для шага apply.
        - reader: адаптер TargetPagedReaderProtocol для обновления кэша (может быть None).
        - check(): проверка доступности target-системы.
        - meta(): типизированные метаданные target.
        - stats(): типизированная статистика.
        - reset(): сброс счётчиков.
        - close(): освобождение ресурсов транспорта (например, httpx.Client).
    """

    @property
    def executor(self) -> RequestExecutorProtocol: ...

    @property
    def reader(self) -> TargetPagedReaderProtocol | None: ...

    def check(self) -> TargetCheckResult: ...

    def meta(self) -> TargetMeta: ...

    def stats(self) -> TargetStats: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class DefaultTargetRuntime:
    """
    Основная (production) реализация TargetRuntime.

    Назначение:
        Фасад над TargetGateway + TargetConnectionConfig.
        Gateway структурно удовлетворяет RequestExecutorProtocol и TargetPagedReaderProtocol.
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
        """Вернуть executor-интерфейс для execute-пайплайнов."""
        return self._gateway  # type: ignore[return-value]

    @property
    def reader(self) -> TargetPagedReaderProtocol | None:
        """Вернуть reader-интерфейс или ``None``, если чтение отключено."""
        return self._gateway if self._has_reader else None  # type: ignore[return-value]

    def check(self) -> TargetCheckResult:
        """Проверить доступность target через health-check gateway."""
        return self._gateway.health_check()

    def meta(self) -> TargetMeta:
        """Вернуть метаданные подключённого target."""
        return TargetMeta(
            target_type=self._config.target_type,
            transport=self._config.transport,
            endpoint=self._config.endpoint,
        )

    def stats(self) -> TargetStats:
        """Вернуть агрегированные счётчики запросов/retry/failures."""
        req, ret, fail = self._gateway.get_stats()
        return TargetStats(
            requests_total=req,
            retries_total=ret,
            failures_total=fail,
        )

    def reset(self) -> None:
        """Сбросить runtime-счётчики gateway."""
        self._gateway.reset_stats()

    def close(self) -> None:
        """Освободить ресурсы транспорта."""
        self._gateway.close()
