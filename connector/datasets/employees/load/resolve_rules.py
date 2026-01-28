from __future__ import annotations

from connector.domain.planning.rules import ResolveRules
from connector.datasets.employees.load.projector import EmployeesProjector
from connector.datasets.employees.load.diff_policy import EmployeesDiffPolicy
from connector.domain.models import ValidationRowResult
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_desired_state(row: NormalizedEmployeesRow, _: ValidationRowResult) -> dict:
    projector = EmployeesProjector()
    return projector.to_desired_state(row)


def build_source_ref(identity) -> dict:
    projector = EmployeesProjector()
    return projector.to_source_ref(identity)


def secret_fields_for_op(op: str, desired_state: dict, existing: dict | None) -> list[str]:
    _ = (desired_state, existing)
    if op == "create":
        return ["password"]
    return []


def build_resolve_rules() -> ResolveRules:
    differ = EmployeesDiffPolicy()
    return ResolveRules(
        build_desired_state=build_desired_state,
        build_source_ref=build_source_ref,
        diff_policy=differ.calculate_changes,
        secret_fields_for_op=secret_fields_for_op,
    )
