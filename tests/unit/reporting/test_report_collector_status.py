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


def test_build_returns_snapshot_isolated_from_later_collector_mutation() -> None:
    report = ReportCollector(run_id="r-snapshot", command="mapping")
    report.add_item(status="OK", row_ref=None, payload=None, errors=[], warnings=[], meta={})
    first = report.build()

    report.add_item(status="FAILED", row_ref=None, payload=None, errors=[], warnings=[], meta={})
    second = report.build()

    assert first.summary.rows_total == 1
    assert len(first.items) == 1
    assert second.summary.rows_total == 2
    assert len(second.items) == 2


def test_build_snapshot_mutation_does_not_change_collector_state() -> None:
    report = ReportCollector(run_id="r-snapshot-mutation", command="mapping")
    report.add_item(status="OK", row_ref=None, payload=None, errors=[], warnings=[], meta={})
    built = report.build()

    built.summary.rows_total = 999
    built.context["mutated"] = True
    built.items.append(built.items[0])

    after = report.build()
    assert after.summary.rows_total == 1
    assert "mutated" not in after.context
    assert len(after.items) == 1
