"""Purpose:
    Политика преобразования stage stats в доменный CommandResult.

Boundary:
    - Содержит только решение о системных кодах результата команды.
    - Не отвечает за сбор row-level report items.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.adapters.stats_accumulator import StageExecutionStats


@dataclass(frozen=True)
class StageCommandResultResolver:
    """Purpose:
        Единый resolver системных кодов по stage-статистике.
    """

    success_code: SystemErrorCode = SystemErrorCode.OK
    failed_code: SystemErrorCode = SystemErrorCode.DATA_INVALID
    conflict_code: SystemErrorCode = SystemErrorCode.CONFLICT

    def resolve(
        self,
        stats: StageExecutionStats,
        *,
        has_conflicts: bool = False,
    ) -> CommandResult:
        """Purpose:
            Построить CommandResult на основе stage snapshot и доменных флагов.
        """
        result = CommandResult()
        if stats.failed_rows > 0:
            result.add_code(self.failed_code)
        else:
            result.add_code(self.success_code)
        if has_conflicts:
            result.add_code(self.conflict_code)
        return result
