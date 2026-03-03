"""Назначение:
    Формальный capability-контракт policy для report layer.

Граница ответственности:
    - Описывает только профиль и capability-флаги детализации отчёта.
    - Вычисляет эффективные возможности с учетом CLI/config override.
    - Не знает о runtime orchestration и не пишет report items напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from connector.domain.reporting.policy_matrix import REPORT_POLICY_PROFILE_MATRIX


class ReportPolicyProfile(str, Enum):
    """Назначение:
        Канонические профили детализации отчёта.
    """

    MINIMAL = "minimal"
    STANDARD = "standard"
    DEBUG = "debug"


@dataclass(frozen=True)
class ReportPolicyCapabilities:
    """Назначение:
        Набор capability-флагов, определяющий уровень детализации отчёта.
    """

    include_ok_items: bool
    include_failed_items: bool
    include_skipped_items: bool
    include_payload_masked: bool
    include_upstream_diagnostics: bool
    include_subsystem_metrics: bool
    include_runtime_secondary_as_items: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "include_ok_items": self.include_ok_items,
            "include_failed_items": self.include_failed_items,
            "include_skipped_items": self.include_skipped_items,
            "include_payload_masked": self.include_payload_masked,
            "include_upstream_diagnostics": self.include_upstream_diagnostics,
            "include_subsystem_metrics": self.include_subsystem_metrics,
            "include_runtime_secondary_as_items": self.include_runtime_secondary_as_items,
        }


@dataclass(frozen=True)
class ReportPolicy:
    """Назначение:
        Policy-контракт report слоя: профиль + capability-модель.
    """

    profile: ReportPolicyProfile
    capabilities: ReportPolicyCapabilities

    @classmethod
    def minimal(cls) -> "ReportPolicy":
        return cls.from_profile(ReportPolicyProfile.MINIMAL)

    @classmethod
    def standard(cls) -> "ReportPolicy":
        return cls.from_profile(ReportPolicyProfile.STANDARD)

    @classmethod
    def debug(cls) -> "ReportPolicy":
        return cls.from_profile(ReportPolicyProfile.DEBUG)

    @classmethod
    def from_profile(cls, profile: ReportPolicyProfile | str | None) -> "ReportPolicy":
        resolved_profile = _normalize_profile(profile)
        matrix = REPORT_POLICY_PROFILE_MATRIX[resolved_profile.value]
        return cls(
            profile=resolved_profile,
            capabilities=ReportPolicyCapabilities(**_validate_matrix_entry(matrix)),
        )

    @classmethod
    def from_context(cls, value: Mapping[str, Any] | "ReportPolicy" | None) -> "ReportPolicy":
        if isinstance(value, ReportPolicy):
            return value
        if not isinstance(value, Mapping):
            return cls.standard()
        profile_raw = value.get("profile")
        return cls.from_profile(profile_raw if isinstance(profile_raw, str) else None)

    def to_context_payload(
        self,
        *,
        cli_include_skipped: bool,
        effective_include_skipped_items: bool,
    ) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "capabilities": self.capabilities.to_dict(),
            "cli_include_skipped": bool(cli_include_skipped),
            "effective_include_skipped_items": bool(effective_include_skipped_items),
        }

    def resolve_include_ok_items(self, cli_include_ok_items: bool) -> bool:
        return self.capabilities.include_ok_items and bool(cli_include_ok_items)

    def resolve_include_upstream_diagnostics(self, requested: bool) -> bool:
        return self.capabilities.include_upstream_diagnostics and bool(requested)

    def resolve_include_skipped_items(self, cli_include_skipped: bool) -> bool:
        """Контракт:
            effective_include_skipped_items = capability AND cli_override.
        """
        return self.capabilities.include_skipped_items and bool(cli_include_skipped)


def resolve_report_policy(
    policy_context: Mapping[str, Any] | None = None,
    report_policy: ReportPolicy | None = None,
) -> ReportPolicy:
    """Назначение:
        Разрешить policy для reporting-адаптеров во внешнем слое композиции.

    Контракт:
        - `StageResultReporter` получает уже разрешенный policy и не читает context.
        - Если явный policy не передан, используется `policy_context`.
        - При отсутствии context применяется профиль `standard`.
    """
    if report_policy is not None:
        return report_policy
    return ReportPolicy.from_context(policy_context)


def _normalize_profile(profile: ReportPolicyProfile | str | None) -> ReportPolicyProfile:
    if isinstance(profile, ReportPolicyProfile):
        return profile
    if isinstance(profile, str) and profile.strip():
        value = profile.strip().lower()
        return ReportPolicyProfile(value)
    return ReportPolicyProfile.STANDARD


def _validate_matrix_entry(entry: Mapping[str, Any]) -> dict[str, bool]:
    expected_keys = set(ReportPolicyCapabilities.__annotations__.keys())
    provided_keys = set(entry.keys())
    missing = expected_keys - provided_keys
    extra = provided_keys - expected_keys
    if missing:
        missing_keys = ", ".join(sorted(missing))
        raise ValueError(f"Policy matrix entry is missing keys: {missing_keys}")
    if extra:
        extra_keys = ", ".join(sorted(extra))
        raise ValueError(f"Policy matrix entry has unknown keys: {extra_keys}")
    return {key: bool(entry[key]) for key in expected_keys}


__all__ = [
    "ReportPolicy",
    "ReportPolicyCapabilities",
    "ReportPolicyProfile",
    "resolve_report_policy",
]
