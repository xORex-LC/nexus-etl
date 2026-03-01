"""
Назначение:
    Доменные объекты и сборщик отчётов.
"""

from connector.domain.reporting.policy import (
    ReportPolicy,
    ReportPolicyCapabilities,
    ReportPolicyProfile,
    resolve_report_policy,
)

__all__ = [
    "ReportPolicy",
    "ReportPolicyCapabilities",
    "ReportPolicyProfile",
    "resolve_report_policy",
]
