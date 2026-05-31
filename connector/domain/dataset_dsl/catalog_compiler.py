"""
Назначение:
    Компиляция декларативного списка DiagnosticEntrySpec в ErrorCatalog.

Граница ответственности:
    - Owns: маппинг string → enum (SystemErrorCode, DiagnosticSeverity).
    - Does NOT: загрузка DSL, runtime-диагностика.
"""

from __future__ import annotations

from connector.domain.dataset_dsl.specs import DiagnosticEntrySpec
from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticSeverity


_SYSTEM_CODE_MAP: dict[str, SystemErrorCode] = {
    e.value.upper(): e for e in SystemErrorCode
}
_SEVERITY_MAP: dict[str, DiagnosticSeverity] = {e.value: e for e in DiagnosticSeverity}


def _resolve_system_code(raw: str) -> SystemErrorCode:
    normalized = raw.strip().upper()
    result = _SYSTEM_CODE_MAP.get(normalized)
    if result is None:
        raise ValueError(
            f"Unknown system_code '{raw}'. "
            f"Valid values: {', '.join(sorted(_SYSTEM_CODE_MAP))}"
        )
    return result


def _resolve_severity(raw: str) -> DiagnosticSeverity:
    normalized = raw.strip().lower()
    result = _SEVERITY_MAP.get(normalized)
    if result is None:
        raise ValueError(
            f"Unknown severity '{raw}'. "
            f"Valid values: {', '.join(sorted(_SEVERITY_MAP))}"
        )
    return result


def compile_diagnostic_catalog(
    entries: list[DiagnosticEntrySpec],
    *,
    strict: bool,
) -> ErrorCatalog:
    """
    Назначение:
        Скомпилировать декларативные DiagnosticEntrySpec в ErrorCatalog.
    """
    catalog_entries = [
        CatalogEntry(
            diag_code=entry.code,
            system_code=_resolve_system_code(entry.system_code),
            severity=_resolve_severity(entry.severity),
            default_message=entry.message or None,
        )
        for entry in entries
    ]
    return ErrorCatalog(entries=catalog_entries, strict=strict)
