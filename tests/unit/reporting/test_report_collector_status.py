from __future__ import annotations

from connector.domain.reporting.collector import ReportCollector


def test_status_failed_when_rows_blocked_and_no_passed() -> None:
    report = ReportCollector(run_id="r-failed", command="mapping")
    report.add_item(
        status="FAILED",
        row_ref=None,
        payload=None,
        errors=[],
        warnings=[],
        meta={},
    )

    built = report.build()
    assert built.summary.rows_blocked == 1
    assert built.summary.rows_passed == 0
    assert built.status == "FAILED"


def test_status_partial_when_rows_blocked_and_rows_passed() -> None:
    report = ReportCollector(run_id="r-partial", command="mapping")
    report.add_item(
        status="OK",
        row_ref=None,
        payload=None,
        errors=[],
        warnings=[],
        meta={},
    )
    report.add_item(
        status="FAILED",
        row_ref=None,
        payload=None,
        errors=[],
        warnings=[],
        meta={},
    )

    built = report.build()
    assert built.summary.rows_passed == 1
    assert built.summary.rows_blocked == 1
    assert built.status == "PARTIAL"
