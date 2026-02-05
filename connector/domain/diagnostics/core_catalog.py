"""
Назначение:
    Базовый каталог диагностик ядра.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticSeverity


def build_core_catalog(*, strict: bool) -> ErrorCatalog:
    """
    Назначение:
        Сформировать базовый каталог диагностических кодов.
    """
    entries = [
        CatalogEntry("SOURCE_ERROR", SystemErrorCode.IO_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("missing_source_column", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("REQUIRED_FIELD_MISSING", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MATCH_IDENTITY_MISSING", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MATCH_CONFLICT_TARGET", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MATCH_CONFLICT", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MATCH_CONFLICT_SOURCE", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MATCH_DUPLICATE_SOURCE", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.WARNING),
        CatalogEntry("RESOLVE_CONFLICT", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("RESOLVE_TARGET_ID_MISSING", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("RESOLVE_CONFIG_MISSING", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("RESOLVE_MAX_ATTEMPTS", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("RESOLVE_PENDING", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.WARNING),
        CatalogEntry("RESOLVE_EXPIRED", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("CACHE_ERROR", SystemErrorCode.CACHE_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("ENRICH_FATAL_POLICY_UNSET", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.WARNING),
        CatalogEntry("ENRICH_MULTI_TARGET_UNSUPPORTED", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("ENRICH_MISSING_KEY", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("ENRICH_PROVIDER_ERROR", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("ENRICH_NO_CANDIDATES", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.WARNING),
        CatalogEntry("ENRICH_AMBIGUOUS", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.WARNING),
        CatalogEntry("ENRICH_TARGET_MISMATCH", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SECRET_STORE_ERROR", SystemErrorCode.IO_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SECRET_REQUIRED", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("INVALID_JSON", SystemErrorCode.IO_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("INVALID_ITEMS_FORMAT", SystemErrorCode.IO_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("NETWORK_ERROR", SystemErrorCode.INFRA_UNAVAILABLE, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("MAX_PAGES_EXCEEDED", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("TARGET_ID_CONFLICT", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("INTERNAL_ERROR", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("UNEXPECTED_ERROR", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("API_ERROR", SystemErrorCode.INTERNAL_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_HTTP_ERROR", SystemErrorCode.INFRA_UNAVAILABLE, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_TIMEOUT", SystemErrorCode.INFRA_TIMEOUT, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_IO_ERROR", SystemErrorCode.IO_ERROR, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_UNAVAILABLE", SystemErrorCode.INFRA_UNAVAILABLE, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_UNAUTHORIZED", SystemErrorCode.AUTH_UNAUTHORIZED, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_FORBIDDEN", SystemErrorCode.AUTH_FORBIDDEN, severity=DiagnosticSeverity.ERROR),
        CatalogEntry("SINK_CONFLICT", SystemErrorCode.CONFLICT, severity=DiagnosticSeverity.ERROR),
    ]
    return ErrorCatalog(entries, strict=strict)
