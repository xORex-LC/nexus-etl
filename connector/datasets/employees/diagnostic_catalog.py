from __future__ import annotations

from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog
from connector.domain.diagnostics.system_codes import SystemErrorCode
from connector.domain.models import DiagnosticSeverity


def build_employees_catalog(strict: bool = False) -> ErrorCatalog:
    """
    Назначение:
        Каталог диагностических кодов, специфичных для employees.
    """
    entries = [
        CatalogEntry(
            diag_code="INVALID_AVATAR_ID",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="avatarId must be empty or null",
        ),
        CatalogEntry(
            diag_code="USR_ORG_TAB_CONFLICT",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="usr_org_tab_num conflicts with existing row",
        ),
        CatalogEntry(
            diag_code="TARGET_ID_MISSING",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="target_id is required",
        ),
        CatalogEntry(
            diag_code="MATCH_KEY_MISSING",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="match_key is required",
        ),
        CatalogEntry(
            diag_code="INVALID_INT",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="invalid integer value",
        ),
        CatalogEntry(
            diag_code="INVALID_EMAIL",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="email has invalid format",
        ),
        CatalogEntry(
            diag_code="INVALID_BOOLEAN",
            system_code=SystemErrorCode.DATA_INVALID,
            severity=DiagnosticSeverity.ERROR,
            default_message="invalid boolean value",
        ),
    ]
    return ErrorCatalog(entries=entries, strict=strict)


__all__ = ["build_employees_catalog"]
