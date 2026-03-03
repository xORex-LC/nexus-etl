"""Purpose:
    Stage-level аккумулятор и immutable snapshot статистики.

Boundary:
    - Хранит только агрегированные числовые counters.
    - Не знает о report item storage и не формирует CommandResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class StageExecutionStats:
    """Purpose:
        Immutable snapshot counters для одной transform/planning стадии.
    """

    rows_total: int
    ok_rows: int
    failed_rows: int
    warnings_rows: int
    vault_candidates_rows: int
    vault_candidates_fields_total: int

    def to_context_payload(self, *, ok_label: str, failed_label: str) -> dict[str, int]:
        """Purpose:
            Проецировать snapshot в стандартный report context block.
        """
        return {
            "rows_total": self.rows_total,
            ok_label: self.ok_rows,
            failed_label: self.failed_rows,
            "warnings_rows": self.warnings_rows,
            "vault_candidates_rows": self.vault_candidates_rows,
            "vault_candidates_fields_total": self.vault_candidates_fields_total,
        }


class ExecutionStatsAccumulator:
    """Purpose:
        Mutable runtime accumulator для stage counters.

    Contract:
        - Заполняется по мере обработки каждого result.
        - Публикация наружу только через immutable `snapshot()`.
    """

    def __init__(self) -> None:
        self._rows_total = 0
        self._ok_rows = 0
        self._failed_rows = 0
        self._warnings_rows = 0
        self._vault_candidates_rows = 0
        self._vault_candidates_fields_total = 0

    def on_row(self, *, has_errors: bool, has_warnings: bool) -> None:
        """Purpose:
            Учесть одну обработанную строку по статусным counters.
        """
        self._rows_total += 1
        if has_errors:
            self._failed_rows += 1
        else:
            self._ok_rows += 1
        if has_warnings:
            self._warnings_rows += 1

    def on_secret_fields(self, secret_fields: Mapping[str, object] | list[str]) -> None:
        """Purpose:
            Учесть статистику секретных полей для vault diagnostics.
        """
        count = len(secret_fields)
        if count <= 0:
            return
        self._vault_candidates_rows += 1
        self._vault_candidates_fields_total += count

    def snapshot(self) -> StageExecutionStats:
        """Purpose:
            Вернуть immutable snapshot текущего состояния аккумулятора.
        """
        return StageExecutionStats(
            rows_total=self._rows_total,
            ok_rows=self._ok_rows,
            failed_rows=self._failed_rows,
            warnings_rows=self._warnings_rows,
            vault_candidates_rows=self._vault_candidates_rows,
            vault_candidates_fields_total=self._vault_candidates_fields_total,
        )
