from __future__ import annotations

from types import SimpleNamespace

from connector.delivery.commands import import_plan as import_plan_command
from connector.domain.models import RowRef
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.events import SetRowCountersEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import ReportSink


def _app_config(default_cli_include_skipped: bool = True):
    return SimpleNamespace(
        observability=SimpleNamespace(
            reporting=SimpleNamespace(include_skipped=default_cli_include_skipped)
        )
    )


def test_import_plan_include_skipped_true_stores_items_and_keeps_rows_skipped() -> None:
    context = InMemoryReportContext(run_id="r-plan-include", command="import-plan")
    sink = ReportSink(context)
    policy = ReportPolicy.standard()
    opts = import_plan_command.Options(report_include_skipped=True)
    effective = import_plan_command._resolve_effective_include_skipped_items(  # noqa: SLF001
        opts=opts,
        app_config=_app_config(True),
        report_policy=policy,
    )
    sink.emit(
        SetRowCountersEvent(
            rows_total=3,
            rows_passed=2,
            rows_blocked=0,
            rows_with_warnings=0,
            rows_skipped=1,
        )
    )
    import_plan_command._emit_skipped_report_item(  # noqa: SLF001
        report_sink=sink,
        row_ref=RowRef(line_no=None, row_id="line:3", identity_primary=None, identity_value=None),
        store=effective,
    )

    built = ReportAssembler(context=context).assemble()
    assert effective is True
    assert built.summary.rows_skipped == 1
    assert len(built.items) == 1
    assert built.items[0].status == "SKIPPED"
    assert built.items[0].row_ref is not None
    assert built.items[0].row_ref.line_no is None


def test_import_plan_include_skipped_false_does_not_store_items_but_keeps_summary() -> None:
    context = InMemoryReportContext(run_id="r-plan-no-include", command="import-plan")
    sink = ReportSink(context)
    policy = ReportPolicy.standard()
    opts = import_plan_command.Options(report_include_skipped=False)
    effective = import_plan_command._resolve_effective_include_skipped_items(  # noqa: SLF001
        opts=opts,
        app_config=_app_config(True),
        report_policy=policy,
    )
    sink.emit(
        SetRowCountersEvent(
            rows_total=3,
            rows_passed=2,
            rows_blocked=0,
            rows_with_warnings=0,
            rows_skipped=1,
        )
    )
    import_plan_command._emit_skipped_report_item(  # noqa: SLF001
        report_sink=sink,
        row_ref=RowRef(line_no=3, row_id="line:3", identity_primary=None, identity_value=None),
        store=effective,
    )

    built = ReportAssembler(context=context).assemble()
    assert effective is False
    assert built.summary.rows_skipped == 1
    assert len(built.items) == 0


def test_import_plan_capability_blocks_skipped_items_even_when_cli_true() -> None:
    policy = ReportPolicy.minimal()
    opts = import_plan_command.Options(report_include_skipped=True)
    effective = import_plan_command._resolve_effective_include_skipped_items(  # noqa: SLF001
        opts=opts,
        app_config=_app_config(True),
        report_policy=policy,
    )

    assert effective is False
