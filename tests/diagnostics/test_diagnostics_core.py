from __future__ import annotations

from connector.domain.diagnostics import DiagnosticFactory
from connector.domain.diagnostics.catalog import ErrorCatalog, CatalogEntry
from connector.domain.diagnostics.exceptions import UnknownDiagnosticCodeError
from connector.domain.diagnostics.system_codes import SystemErrorCode
from connector.domain.diagnostics.translator import Translator
from connector.domain.models import DiagnosticSeverity, DiagnosticStage, RowRef
from connector.domain.ports.execution import ExecutionResult
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord


def test_factory_strict_unknown_raises() -> None:
    catalog = ErrorCatalog(strict=True)
    factory = DiagnosticFactory(catalog)
    try:
        factory.error(DiagnosticStage.VALIDATE, code="UNKNOWN_CODE")
    except UnknownDiagnosticCodeError:
        return
    assert False, "Expected UnknownDiagnosticCodeError for strict catalog"


def test_factory_permissive_unknown_allows() -> None:
    catalog = ErrorCatalog(strict=False)
    factory = DiagnosticFactory(catalog)
    item = factory.error(DiagnosticStage.VALIDATE, code="UNKNOWN_CODE")
    assert item.code == "UNKNOWN_CODE"
    assert item.severity == DiagnosticSeverity.ERROR


def test_severity_resolution_prefers_catalog_then_fallback() -> None:
    catalog = ErrorCatalog(
        entries=[CatalogEntry("TEST_WARN", SystemErrorCode.DATA_INVALID, severity=DiagnosticSeverity.WARNING)],
        strict=False,
    )
    factory = DiagnosticFactory(catalog)
    item = factory.error(DiagnosticStage.VALIDATE, code="TEST_WARN")
    assert item.severity == DiagnosticSeverity.WARNING


def test_translator_maps_execution_result() -> None:
    catalog = ErrorCatalog(strict=False)
    translator = Translator(catalog)
    result = ExecutionResult(
        ok=False,
        status_code=401,
        response_json=None,
        error_code=SystemErrorCode.AUTH_UNAUTHORIZED,
        error_message="unauthorized",
        error_reason=None,
        error_details=None,
    )
    diag = translator.from_execution_result(DiagnosticStage.SINK, result)
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
