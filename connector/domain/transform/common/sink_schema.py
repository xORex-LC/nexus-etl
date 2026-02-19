"""
Назначение:
    Валидация результата стадий против sink-схемы.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from connector.domain.dsl.issues import DslIssue, DslSeverity
from connector.domain.transform_dsl.specs import SinkSpec, SinkFieldSpec


def validate_sink_row(
    row: Mapping[str, Any],
    spec: SinkSpec,
    *,
    check_types: bool,
) -> list[DslIssue]:
    """
    Назначение:
        Проверить результат против sink-схемы и вернуть список DslIssue.
    """
    issues: list[DslIssue] = []
    for field in spec.sink.fields:
        _validate_field(row, field, check_types, issues)
    return issues


def validate_sink_fields(
    row: Mapping[str, Any],
    spec: SinkSpec,
    *,
    fields: Iterable[str],
    check_types: bool,
) -> list[DslIssue]:
    """
    Назначение:
        Проверить только указанные поля sink-схемы и вернуть список DslIssue.
    """
    issues: list[DslIssue] = []
    indexed = {
        sink_field.name: sink_field
        for sink_field in (*spec.sink.fields, *spec.sink.system_fields)
    }
    for name in fields:
        field = indexed.get(name)
        if field is None:
            continue
        _validate_field(row, field, check_types, issues)
    return issues


def _validate_field(
    row: Mapping[str, Any],
    field: SinkFieldSpec,
    check_types: bool,
    issues: list[DslIssue],
) -> None:
    name = field.name
    has_key = name in row
    value = row.get(name)

    if field.required:
        if not has_key:
            issues.append(_missing_required_issue(name))
            return
        if value is None and not field.nullable:
            issues.append(_missing_required_issue(name))
            return
        if isinstance(value, str) and value.strip() == "" and not field.nullable:
            issues.append(_missing_required_issue(name))
            return

    if not check_types:
        return
    if value is None:
        return
    if field.nullable and value is None:
        return
    if not _matches_type(value, field.type):
        issues.append(_type_issue(name, field.type, value))


def _missing_required_issue(field: str) -> DslIssue:
    return DslIssue(
        code="SINK_REQUIRED_MISSING",
        message=f"{field} is required by sink schema",
        field=field,
        severity=DslSeverity.ERROR,
    )


def _type_issue(field: str, expected: str, value: Any) -> DslIssue:
    return DslIssue(
        code="SINK_TYPE_INVALID",
        message=f"{field} has invalid type (expected {expected})",
        field=field,
        details={"expected": expected, "actual": type(value).__name__},
        severity=DslSeverity.ERROR,
    )


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "bool":
        if isinstance(value, bool):
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"true", "false", "1", "0", "yes", "no", "y", "n"}
        return False
    if expected == "int":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, str):
            return value.strip().isdigit()
        return False
    if expected == "float":
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                float(value)
                return True
            except ValueError:
                return False
        return False
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "list":
        return isinstance(value, list)
    return True
