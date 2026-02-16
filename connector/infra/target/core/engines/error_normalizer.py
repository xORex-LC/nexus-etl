"""
Модуль нормализации ошибок для target gateway/runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.models import TargetFaultKind


@dataclass(frozen=True, slots=True)
class NormalizedFault:
    fault_kind: TargetFaultKind
    error_code: SystemErrorCode


class TargetErrorNormalizer:
    """Тонкий адаптер: классификация через kernel + маппинг в системный код."""

    def __init__(self, kernel: TargetKernel) -> None:
        self._kernel = kernel

    def from_status(self, status_code: int | None) -> NormalizedFault:
        fault = self._kernel.classify_fault(status_code=status_code)
        return NormalizedFault(
            fault_kind=fault,
            error_code=self._kernel.system_error_code(fault),
        )

    def from_error_code(self, error_code: str | None) -> NormalizedFault:
        fault = self._kernel.classify_fault(error_code=error_code)
        return NormalizedFault(
            fault_kind=fault,
            error_code=self._kernel.system_error_code(fault),
        )

    def from_status_or_code(
        self,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> NormalizedFault:
        fault = self._kernel.classify_fault(
            status_code=status_code,
            error_code=error_code,
        )
        return NormalizedFault(
            fault_kind=fault,
            error_code=self._kernel.system_error_code(fault),
        )
