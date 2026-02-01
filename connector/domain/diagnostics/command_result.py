from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from connector.domain.diagnostics.policies import (
    ExitCodePolicy,
    StopPolicy,
    default_exit_policy,
    default_stop_policy,
    resolve_primary_code,
)
from connector.domain.diagnostics.system_codes import SystemErrorCode
from connector.domain.models import DiagnosticItem


@dataclass
class CommandResult:
    """
    Назначение:
        Унифицированный результат выполнения команды/usecase.
    """

    system_codes: set[SystemErrorCode] = field(default_factory=set)
    diagnostics: list[DiagnosticItem] = field(default_factory=list)
    summary: dict | None = None

    def add_code(self, code: SystemErrorCode) -> None:
        self.system_codes.add(code)

    def add_codes(self, codes: Iterable[SystemErrorCode]) -> None:
        for code in codes:
            self.system_codes.add(code)

    def add_diagnostics(self, diagnostics: Iterable[DiagnosticItem], catalog) -> None:
        for item in diagnostics:
            self.diagnostics.append(item)
            self.system_codes.add(catalog.classify(item.code))

    def merge(self, other: "CommandResult") -> None:
        self.system_codes.update(other.system_codes)
        self.diagnostics.extend(other.diagnostics)

    def primary_code(self, stop_policy: StopPolicy | None = None) -> SystemErrorCode:
        return resolve_primary_code(self.system_codes, stop_policy or default_stop_policy())

    def exit_code(
        self,
        exit_policy: ExitCodePolicy | None = None,
        stop_policy: StopPolicy | None = None,
    ) -> int:
        policy = exit_policy or default_exit_policy()
        return policy.exit_code(self.primary_code(stop_policy))

    @property
    def ok(self) -> bool:
        return len(self.system_codes) == 0 or self.system_codes == {SystemErrorCode.OK}
