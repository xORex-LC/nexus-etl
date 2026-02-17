from __future__ import annotations

from typing import Protocol

from connector.infra.target.core.runtime import TargetRuntime


class TargetProvider(Protocol):
    """Контракт провайдера для сборки target runtime."""

    target_type: str

    def build_core_runtime(
        self,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime: ...
