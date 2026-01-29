from __future__ import annotations

from typing import Any

from connector.domain.models import DiagnosticStage, Identity, MatchStatus, RowRef, ValidationErrorItem
from connector.domain.planning.match_models import MatchedRow, build_fingerprint
from connector.domain.planning.rules import MatchingRules, ResolveRules
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

        identity = self.matching_rules.build_identity(row, validation)
        identity_value = identity.primary_value
        if not identity_value:
            return TransformResult(
                record=validated.record,
                row=None,
                row_ref=validation.row_ref,
                match_key=validated.match_key,
                meta=validated.meta,
                secret_candidates=validated.secret_candidates,
                errors=[*_make_match_error("MATCH_IDENTITY_MISSING", identity.primary, "identity value is empty")],
                warnings=[*validated.warnings],
            )

        desired_state = self.resolve_rules.build_desired_state(row, validation)
        fingerprint, fingerprint_fields = build_fingerprint(
            desired_state,
            ignored_fields=self.matching_rules.ignored_fields,
        )

        candidates = self.cache_repo.find(
            self.dataset,
            {identity.primary: identity_value},
            include_deleted=self.include_deleted,
        )
        if len(candidates) > 1:
            error = ValidationErrorItem(
                stage=DiagnosticStage.MATCH,
                code="MATCH_CONFLICT_TARGET",
                field=identity.primary,
                message="multiple existing candidates found",
            )
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

        match_status = MatchStatus.NOT_FOUND
        existing = None
        if candidates:
            match_status = MatchStatus.MATCHED
            existing = candidates[0]

        links = {}
        if self.matching_rules.build_links:
            links = self.matching_rules.build_links(row, validation)

        matched_row = MatchedRow(
            row_ref=validation.row_ref or RowRef(
                line_no=validation.line_no,
                row_id=f"line:{validation.line_no}",
                identity_primary=identity.primary,
                identity_value=identity_value,
            ),
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
            row_ref=validation.row_ref,
            match_key=validated.match_key,
            meta=validated.meta,
            secret_candidates=validated.secret_candidates,
            errors=[*validated.errors],
            warnings=[*validated.warnings],
        )


def _make_match_error(code: str, field: str | None, message: str) -> list[ValidationErrorItem]:
    return [
        ValidationErrorItem(
            stage=DiagnosticStage.MATCH,
            code=code,
            field=field,
            message=message,
        )
    ]
