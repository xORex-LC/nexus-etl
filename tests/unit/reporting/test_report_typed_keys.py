from __future__ import annotations

from pathlib import Path

from connector.domain.reporting.collector import ReportCollector
from connector.domain.reporting.contracts import ReportContextKey, ReportOpKey


def test_collector_accepts_typed_context_and_ops_keys() -> None:
    report = ReportCollector(run_id="r-typed-keys", command="mapping")
    report.set_context(ReportContextKey.RUNTIME, {"log_file": "log.txt"})
    report.add_op(ReportOpKey.CREATE, ok=1, count=1)

    built = report.build()
    assert "runtime" in built.context
    assert "create" in built.summary.ops


def test_connector_code_has_no_magic_string_set_context_calls() -> None:
    project_root = Path(__file__).resolve().parents[3]
    offenders = _find_magic_string_calls(project_root, method_name="set_context")
    assert offenders == []


def test_connector_code_has_no_magic_string_op_calls() -> None:
    project_root = Path(__file__).resolve().parents[3]
    offenders = [
        *_find_magic_string_calls(project_root, method_name="add_op"),
        *_find_magic_string_calls(project_root, method_name="merge_op_fields"),
    ]
    assert offenders == []


def _find_magic_string_calls(project_root: Path, *, method_name: str) -> list[str]:
    offenders: list[str] = []
    for path in (project_root / "connector").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        marker = f".{method_name}(\""
        if marker in text:
            offenders.append(str(path.relative_to(project_root)))
    return sorted(offenders)
