"""
Назначение:
    Нормализация mapped-данных по DSL-правилам.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.issues import DslIssue, DslSeverity
from connector.domain.transform.dsl.specs import NormalizeRule, NormalizeSpec

T = TypeVar("T")
RowBuilder = Callable[[dict[str, Any]], T]


class NormalizerCore(Generic[T]):
    """
    Назначение/ответственность:
        Применяет DSL-правила нормализации к mapped-строке.
    """

    def __init__(
        self,
        spec: NormalizeSpec,
        *,
        engine: TransformationEngine,
        catalog: ErrorCatalog,
        row_builder: RowBuilder[T] | None = None,
    ) -> None:
        self.spec = spec
        self.catalog = catalog
        self.row_builder = row_builder
        self.engine = engine

    def normalize(self, source: TransformResult[Any]) -> TransformResult[T]:
        """
        Назначение:
            Нормализовать строку и вернуть TransformResult.
        """
        if source.row is None:
            return TransformResult(
                record=source.record,
                row=None,
                row_ref=source.row_ref,
                match_key=source.match_key,
                meta=source.meta,
                secret_candidates=source.secret_candidates,
                errors=source.errors,
                warnings=source.warnings,
            )

        source_values = _to_mapping(source.row)
        if source_values is None:
            return TransformResult(
                record=source.record,
                row=None,
                row_ref=source.row_ref,
                match_key=source.match_key,
                meta=source.meta,
                secret_candidates=source.secret_candidates,
                errors=source.errors,
                warnings=source.warnings,
            )

        normalized_values: dict[str, Any] = dict(source_values)
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []

        for rule in self.spec.normalize.rules:
            value = normalized_values.get(rule.field)
            if not rule.ops:
                continue
            result = self.engine.apply(value, rule.ops)
            for issue in result.issues:
                self._append_issue(errors, warnings, rule, source, issue)
            normalized_values[rule.field] = result.value

        row: T | None
        if errors:
            row = None
        elif self.row_builder is None:
            row = normalized_values  # type: ignore[assignment]
        else:
            if isinstance(self.row_builder, type) and is_dataclass(self.row_builder):
                row = self.row_builder(**normalized_values)  # type: ignore[call-arg]
            else:
                row = self.row_builder(normalized_values)

        return TransformResult(
            record=source.record,
            row=row,
            row_ref=source.row_ref,
            match_key=source.match_key,
            meta=source.meta,
            secret_candidates=source.secret_candidates,
            errors=(*source.errors, *errors),
            warnings=(*source.warnings, *warnings),
        )

    def _append_issue(
        self,
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        rule: NormalizeRule,
        source: TransformResult[Any],
        issue: DslIssue,
    ) -> None:
        as_warning = issue.severity == DslSeverity.WARNING
        if rule.on_error == "warn":
            as_warning = True
        if as_warning:
            warnings.append(
                diag_warning(
                    stage=DiagnosticStage.NORMALIZE,
                    code=issue.code,
                    field=rule.field,
                    message=issue.message,
                    details=issue.details,
                    record_ref=source.row_ref,
                    catalog=self.catalog,
                )
            )
            return
        errors.append(
            diag_error(
                stage=DiagnosticStage.NORMALIZE,
                code=issue.code,
                field=rule.field,
                message=issue.message,
                details=issue.details,
                record_ref=source.row_ref,
                catalog=self.catalog,
            )
        )


def _to_mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    return value.__dict__
