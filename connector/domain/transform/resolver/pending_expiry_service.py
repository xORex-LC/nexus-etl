"""
Назначение:
    Реализация IPendingExpiryService — sweep и drain expired pending links.

    PendingExpiryService инкапсулирует логику, вынесенную из ResolveCore:
    - накопление expired links в буфере (_expired)
    - интервальный guard (не вызывать cache_gateway чаще, чем раз в N секунд)
    - drain для передачи наружу (PipelineHooks → use-case)

Вызов sweep():
    Триггером для sweep() служит PipelineHooks.on_stage_complete.
    ResolveCore больше не вызывает sweep напрямую.
"""

from __future__ import annotations

from datetime import datetime, timezone

from connector.domain.ports.cache.models import PendingLink
from connector.domain.ports.cache.roles import ResolveRuntimePort
from connector.domain.transform.resolver.resolve_deps import ResolverSettings


class PendingExpiryService:
    """
    Назначение:
        Управляет lifecycle expired pending links.

    Алгоритм sweep():
        1. Проверяет интервал (pending_sweep_interval_seconds).
        2. Вызывает cache_gateway.sweep_expired() если интервал истёк.
        3. Накапливает результат в _expired буфере.

    drain_expired():
        Возвращает накопленный буфер и очищает его.
    """

    def __init__(
        self,
        cache_gateway: ResolveRuntimePort,
        settings: ResolverSettings | None = None,
    ) -> None:
        self._cache_gateway = cache_gateway
        self._settings = settings
        self._last_sweep_at: datetime | None = None
        self._expired: list[PendingLink] = []

    def sweep(self) -> None:
        interval = self._settings.pending_sweep_interval_seconds if self._settings else 0
        if interval <= 0:
            return
        now = datetime.now(timezone.utc)
        if self._last_sweep_at is not None:
            elapsed = (now - self._last_sweep_at).total_seconds()
            if elapsed < interval:
                return
        self._last_sweep_at = now
        expired = self._cache_gateway.sweep_expired(now.isoformat(), reason="expired")
        if expired:
            self._expired.extend(expired)

    def drain_expired(self) -> list[PendingLink]:
        expired = list(self._expired)
        self._expired.clear()
        return expired


__all__ = ["PendingExpiryService"]
