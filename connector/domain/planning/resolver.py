from __future__ import annotations

from typing import Any

from connector.domain.models import DiagnosticStage, MatchStatus, ValidationErrorItem
from connector.domain.planning.match_models import MatchedRow, ResolvedRow, ResolveOp
from connector.domain.planning.rules import ResolveRules


class Resolver:
    """
    Назначение/ответственность:
        Принятие решения по операции и формирование данных для плана.
    """

    def __init__(self, resolve_rules: ResolveRules) -> None:
        self.resolve_rules = resolve_rules

    def resolve(
        self,
        matched: MatchedRow,
        *,
        resource_id_map: dict[str, str],
    ) -> tuple[ResolvedRow | None, list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        if matched.match_status in (MatchStatus.CONFLICT_TARGET, MatchStatus.CONFLICT_SOURCE):
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_CONFLICT",
                    field=matched.identity.primary,
                    message="conflict during match stage",
                )
            )
            return None, errors, warnings

        desired_state = dict(matched.desired_state)
        if self.resolve_rules.merge_policy:
            desired_state = self.resolve_rules.merge_policy(matched.existing, desired_state)

        if matched.source_links:
            for link_name, identity in matched.source_links.items():
                target_id = resource_id_map.get(identity.primary_value)
                if not target_id:
                    errors.append(
                        ValidationErrorItem(
                            stage=DiagnosticStage.RESOLVE,
                            code="RESOLVE_MISSING_EXISTING",
                            field=link_name,
                            message="linked identity not found in source batch",
                        )
                    )
                    return None, errors, warnings
                desired_state[link_name + "_id"] = target_id

        resource_id = _resolve_resource_id(matched, resource_id_map)
        if not resource_id:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_MISSING_EXISTING",
                    field="resource_id",
                    message="resource_id is missing for resolved row",
                )
            )
            return None, errors, warnings

        op, changes = _decide_op(matched, desired_state, self.resolve_rules)

        source_ref = (
            self.resolve_rules.build_source_ref(matched.identity)
            if self.resolve_rules.build_source_ref
            else None
        )
        secret_fields = (
            self.resolve_rules.secret_fields_for_op(op, desired_state, matched.existing)
            if self.resolve_rules.secret_fields_for_op
            else []
        )

        resolved = ResolvedRow(
            row_ref=matched.row_ref,
            identity=matched.identity,
            op=op,
            desired_state=desired_state,
            changes=changes,
            existing=matched.existing,
            resource_id=resource_id,
            source_ref=source_ref,
            secret_fields=secret_fields,
        )
        return resolved, errors, warnings


def _resolve_resource_id(matched: MatchedRow, resource_id_map: dict[str, str]) -> str | None:
    if matched.match_status == MatchStatus.MATCHED:
        existing_id = matched.existing.get("_id") if matched.existing else None
        return str(existing_id) if existing_id is not None else None
    return matched.resource_id or resource_id_map.get(matched.identity.primary_value)


def _decide_op(matched: MatchedRow, desired_state: dict[str, Any], rules: ResolveRules) -> tuple[str, dict[str, Any]]:
    if matched.match_status == MatchStatus.NOT_FOUND:
        return ResolveOp.CREATE, {}

    diff_policy = rules.diff_policy or _default_diff
    changes = diff_policy(matched.existing, desired_state)
    if not changes:
        return ResolveOp.SKIP, {}
    return ResolveOp.UPDATE, changes


def _default_diff(existing: dict[str, Any] | None, desired_state: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return {}
    changes: dict[str, Any] = {}
    for key, value in desired_state.items():
        if key.startswith("__"):
            continue
        if existing.get(key) != value:
            changes[key] = value
    return changes
