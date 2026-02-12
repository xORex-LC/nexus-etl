"""
Назначение:
    Вычисление drift-состояния cache schema по метаданным.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheDriftResult:
    has_drift: bool
    expected: str | None
    actual: str | None
    reason: str | None = None


class CacheDriftService:
    """
    Чистый сервис сравнения schema-version/hash фактов.
    """

    def evaluate_schema_version(
        self,
        *,
        expected: int | str | None,
        actual: str | None,
    ) -> CacheDriftResult:
        expected_norm = str(expected) if expected is not None else None
        actual_norm = str(actual) if actual is not None else None
        if expected_norm is None or actual_norm is None:
            return CacheDriftResult(
                has_drift=False,
                expected=expected_norm,
                actual=actual_norm,
                reason=None,
            )
        has_drift = expected_norm != actual_norm
        reason = "schema_version_mismatch" if has_drift else None
        return CacheDriftResult(
            has_drift=has_drift,
            expected=expected_norm,
            actual=actual_norm,
            reason=reason,
        )
