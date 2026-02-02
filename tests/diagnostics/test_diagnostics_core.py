from __future__ import annotations

from connector.domain.diagnostics import build_catalog, build_error
from connector.domain.diagnostics.catalog import ErrorCatalog, CatalogEntry, build_warning
from connector.domain.diagnostics.exceptions import UnknownDiagnosticCodeError
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.diagnostics.context import get_catalog
from connector.domain.diagnostics.exceptions import DiagnosticContextNotConfiguredError
from connector.domain.diagnostics.translator import translate_execution_result
from connector.domain.models import DiagnosticSeverity, DiagnosticStage, RowRef
from connector.domain.ports.execution import ExecutionResult
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord


def test_factory_strict_unknown_raises() -> None:
    catalog = ErrorCatalog(strict=True)
    try:
        build_error(catalog=catalog, stage=DiagnosticStage.VALIDATE, code="UNKNOWN_CODE")
    except UnknownDiagnosticCodeError:
        return
    assert False, "Expected UnknownDiagnosticCodeError for strict catalog"


def test_factory_permissive_unknown_allows() -> None:
    catalog = ErrorCatalog(strict=False)
    item = build_error(catalog=catalog, stage=DiagnosticStage.VALIDATE, code="UNKNOWN_CODE")
    assert item.code == "UNKNOWN_CODE"
    assert item.severity == DiagnosticSeverity.ERROR


def test_severity_resolution_prefers_catalog_then_fallback() -> None:
    catalog = ErrorCatalog(
        entries=[CatalogEntry("TEST_WARN", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.WARNING)],
        strict=False,
    )
    item = build_warning(catalog=catalog, stage=DiagnosticStage.VALIDATE, code="TEST_WARN")
    assert item.severity == DiagnosticSeverity.WARNING


def test_translator_maps_execution_result() -> None:
    catalog = ErrorCatalog(strict=False)
    result = ExecutionResult(
        ok=False,
        status_code=401,
        response_json=None,
        error_code=SystemErrorCode.AUTH_UNAUTHORIZED,
        error_message="unauthorized",
        error_reason=None,
        error_details=None,
    )
    diag = translate_execution_result(catalog, DiagnosticStage.SINK, result)
    assert diag.code == "SINK_UNAUTHORIZED"


def test_transform_result_add_error_attaches_row_ref() -> None:
    row_ref = RowRef(line_no=1, row_id="row:1", identity_primary=None, identity_value=None)
    result = TransformResult(
        record=SourceRecord(line_no=1, record_id="row:1", values={}),
        row=None,
        row_ref=row_ref,
        match_key=None,
    )
    item = result.add_error(stage=DiagnosticStage.VALIDATE, code="REQUIRED_FIELD_MISSING")
    assert item.record_ref == row_ref


def test_get_catalog_requires_configure() -> None:
    from connector.domain.diagnostics import context as diag_context

    token = diag_context._context_var.set(None)
    try:
        try:
            _ = get_catalog()
        except DiagnosticContextNotConfiguredError:
            return
        assert False, "Expected DiagnosticContextNotConfiguredError when diagnostics not configured"
    finally:
        diag_context._context_var.reset(token)


def test_build_catalog_merges_dataset_codes_in_strict_mode() -> None:
    catalog = build_catalog("employees", strict=True)
    item = build_error(catalog=catalog, stage=DiagnosticStage.VALIDATE, code="INVALID_EMAIL")
    assert item.code == "INVALID_EMAIL"


def test_build_catalog_strict_without_dataset_rejects_dataset_code() -> None:
    catalog = build_catalog(None, strict=True)
    try:
        build_error(catalog=catalog, stage=DiagnosticStage.VALIDATE, code="INVALID_EMAIL")
    except UnknownDiagnosticCodeError:
        return
    assert False, "Expected UnknownDiagnosticCodeError without dataset catalog"


def test_translator_preserves_infra_timeout_code() -> None:
    catalog = build_catalog(None, strict=True)
    result = ExecutionResult(
        ok=False,
        status_code=None,
        response_json=None,
        error_code=SystemErrorCode.INFRA_TIMEOUT,
        error_message="timeout",
        error_reason=None,
        error_details=None,
    )
    diag = translate_execution_result(catalog, DiagnosticStage.SINK, result)
    assert diag.code == "SINK_TIMEOUT"
