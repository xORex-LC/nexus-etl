"""
Назначение:
    Dry-run executor для import-apply команды без обращения к target.
"""

from __future__ import annotations

from connector.domain.ports.target.execution import ExecutionResult, RequestExecutorProtocol, RequestSpec


class DryRunExecutor(RequestExecutorProtocol):
    """Исполнитель-заглушка: любой `RequestSpec` завершает как успешный no-op."""

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        """Вернуть успешный результат без payload и без side effect."""
        _ = spec
        return ExecutionResult(ok=True, answer_code=None, response_payload=None)


__all__ = ["DryRunExecutor"]
