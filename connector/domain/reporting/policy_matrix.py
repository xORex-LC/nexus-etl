"""Назначение:
    Каноническая матрица capability-профилей report policy.

Граница ответственности:
    - Хранит только декларативные preset-значения.
    - Не содержит runtime/reporting логики.
"""

from __future__ import annotations


REPORT_POLICY_PROFILE_MATRIX: dict[str, dict[str, bool]] = {
    "minimal": {
        "include_ok_items": False,
        "include_failed_items": True,
        "include_skipped_items": False,
        "include_payload_masked": False,
        "include_upstream_diagnostics": False,
        "include_subsystem_metrics": False,
        "include_runtime_secondary_as_items": True,
    },
    "standard": {
        "include_ok_items": True,
        "include_failed_items": True,
        "include_skipped_items": True,
        "include_payload_masked": True,
        "include_upstream_diagnostics": False,
        "include_subsystem_metrics": True,
        "include_runtime_secondary_as_items": True,
    },
    "debug": {
        "include_ok_items": True,
        "include_failed_items": True,
        "include_skipped_items": True,
        "include_payload_masked": True,
        "include_upstream_diagnostics": True,
        "include_subsystem_metrics": True,
        "include_runtime_secondary_as_items": True,
    },
}


__all__ = ["REPORT_POLICY_PROFILE_MATRIX"]

