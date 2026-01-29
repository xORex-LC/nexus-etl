from __future__ import annotations

from typing import Any

from connector.domain.models import (
    DiagnosticStage,
    Identity,
    MatchStatus,
    RowRef,
    ValidationErrorItem,
    ValidationRowResult,
)
from connector.domain.planning.match_models import MatchedRow, build_fingerprint
from connector.domain.planning.rules import IdentityRule, MatchingRules, ResolveRules
from connector.domain.ports.cache_repository import CacheRepositoryProtocol
from connector.domain.transform.result import TransformResult
from connector.domain.validation.validated_row import ValidationRow


class Matcher:
    """
    Назначение/ответственность:
        Сопоставление валидированной строки с кэшем/target без принятия решений.
    """

    def __init__(
        self,
        dataset: str,
        cache_repo: CacheRepositoryProtocol,
        matching_rules: MatchingRules,
        resolve_rules: ResolveRules,
        include_deleted: bool,
    ) -> None:
        self.dataset = dataset
        self.cache_repo = cache_repo
        self.matching_rules = matching_rules
        self.resolve_rules = resolve_rules
        self.include_deleted = include_deleted

    def match(self, validated: TransformResult[ValidationRow]) -> TransformResult[MatchedRow]:
        validation_row = validated.row
        if validation_row is None or validation_row.row is None:
            return TransformResult(
                record=validated.record,
                row=None,
                row_ref=validated.row_ref,
                match_key=validated.match_key,
                meta=validated.meta,
                secret_candidates=validated.secret_candidates,
                errors=[*_make_match_error("MATCH_IDENTITY_MISSING", None, "empty validated row")],
                warnings=[*validated.warnings],
            )

        row = validation_row.row
        validation = validation_row.validation

        identity, existing, match_status, error = self._match_identity(row, validation)
        if error is not None:
            return TransformResult(
                record=validated.record,
                row=None,
                row_ref=validation.row_ref,
                match_key=validated.match_key,
                meta=validated.meta,
                secret_candidates=validated.secret_candidates,
                errors=[error],
                warnings=[*validated.warnings],
            )

        identity_value = identity.primary_value if identity else None
        if not identity or not identity_value:
            return TransformResult(
                record=validated.record,
                row=None,
                row_ref=validation.row_ref,
                match_key=validated.match_key,
                meta=validated.meta,
                secret_candidates=validated.secret_candidates,
                errors=[*_make_match_error("MATCH_IDENTITY_MISSING", None, "identity value is empty")],
                warnings=[*validated.warnings],
            )

        desired_state = self.resolve_rules.build_desired_state(row, validation)
        fingerprint, fingerprint_fields = build_fingerprint(
            desired_state,
            ignored_fields=self.matching_rules.ignored_fields,
        )

        links = {}
        if self.matching_rules.build_links:
            links = self.matching_rules.build_links(row, validation)

        row_ref = _ensure_row_ref(validation, identity, identity_value)
        matched_row = MatchedRow(
            row_ref=row_ref,
            identity=identity,
            match_status=match_status,
            desired_state=desired_state,
            existing=existing,
            fingerprint=fingerprint,
            fingerprint_fields=fingerprint_fields,
            source_links=links,
            target_id=getattr(row, "target_id", None),
        )

        return TransformResult(
            record=validated.record,
            row=matched_row,
            row_ref=row_ref,
            match_key=validated.match_key,
            meta=validated.meta,
            secret_candidates=validated.secret_candidates,
            errors=[*validated.errors],
            warnings=[*validated.warnings],
        )

    def _match_identity(
        self,
        row: Any,
        validation: ValidationRowResult,
    ) -> tuple[Identity | None, dict[str, Any] | None, MatchStatus, ValidationErrorItem | None]:
        identity: Identity | None = None
        existing: dict[str, Any] | None = None
        match_status = MatchStatus.NOT_FOUND

        for rule in _iter_identity_rules(self.matching_rules):
            candidate = rule.build_identity(row, validation)
            candidate_value = candidate.primary_value
            if not candidate_value:
                continue
            if identity is None:
                identity = candidate

            candidates = self.cache_repo.find(
                self.dataset,
                {candidate.primary: candidate_value},
                include_deleted=self.include_deleted,
            )
            if len(candidates) > 1:
                return identity, None, MatchStatus.NOT_FOUND, _build_conflict_error(candidate, rule.name)
            if candidates:
                identity = candidate
                existing = candidates[0]
                match_status = MatchStatus.MATCHED
                return identity, existing, match_status, None

        if identity is None:
            return None, None, MatchStatus.NOT_FOUND, _build_identity_error(None, "identity value is empty")
        return identity, None, match_status, None


def _make_match_error(code: str, field: str | None, message: str) -> list[ValidationErrorItem]:
    return [
        ValidationErrorItem(
            stage=DiagnosticStage.MATCH,
            code=code,
            field=field,
            message=message,
        )
    ]


def _ensure_row_ref(validation: ValidationRowResult, identity: Identity, identity_value: str) -> RowRef:
    row_ref = validation.row_ref
    if row_ref is None:
        return RowRef(
            line_no=validation.line_no,
            row_id=f"line:{validation.line_no}",
            identity_primary=identity.primary,
            identity_value=identity_value,
        )
    if row_ref.identity_primary == identity.primary and row_ref.identity_value == identity_value:
        return row_ref
    return RowRef(
        line_no=row_ref.line_no,
        row_id=row_ref.row_id,
        identity_primary=identity.primary,
        identity_value=identity_value,
    )


def _build_identity_error(identity: Identity | None, message: str) -> ValidationErrorItem:
    return ValidationErrorItem(
        stage=DiagnosticStage.MATCH,
        code="MATCH_IDENTITY_MISSING",
        field=identity.primary if identity else None,
        message=message,
    )


def _build_conflict_error(identity: Identity, rule_name: str | None = None) -> ValidationErrorItem:
    suffix = f" ({rule_name})" if rule_name else ""
    return ValidationErrorItem(
        stage=DiagnosticStage.MATCH,
        code="MATCH_CONFLICT_TARGET",
        field=identity.primary,
        message=f"multiple existing candidates found{suffix}",
    )


def _iter_identity_rules(matching_rules: MatchingRules) -> tuple[IdentityRule, ...]:
    if matching_rules.identity_rules:
        return matching_rules.identity_rules
    return (
        IdentityRule(
            name="primary",
            build_identity=matching_rules.build_identity,
        ),
    )
