from __future__ import annotations

from typing import Protocol

from connector.config.app_settings import ApiSettings
from connector.infra.target.runtime import TargetRuntime


class TargetProvider(Protocol):
    """Provider contract for target runtime wiring."""

    target_type: str

    def build_core_runtime(
        self,
        api_settings: ApiSettings,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime: ...

    def build_legacy_runtime(
        self,
        api_settings: ApiSettings,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime: ...
