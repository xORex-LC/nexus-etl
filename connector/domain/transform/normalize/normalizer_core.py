"""
Назначение:
    Нормализация mapped-данных по DSL-правилам.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, Callable, Generic, TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.transform.core.result import TransformResult
from connector.domain.dsl.build_options import NormalizeDslBuildOptions
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.issues import DslIssue
from connector.domain.dsl.diagnostics import append_dsl_issue
from connector.domain.dsl.helpers import apply_ops
from connector.domain.transform.common.values import to_mapping
from connector.domain.dsl.specs import NormalizeRule, NormalizeSpec, SinkSpec
from connector.domain.transform.common.sink_schema import validate_sink_fields, validate_sink_row

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
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder[T] | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> None:
        self.spec = spec
        self.catalog = catalog
        self.row_builder = row_builder
        self.engine = engine
        self.sink_spec = sink_spec
        self.options = options or NormalizeDslBuildOptions()

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

        source_values = to_mapping(source.row)
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
        touched_fields: set[str] = set()
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []

        for rule in self.spec.normalize.rules:
            value = normalized_values.get(rule.field)
            if not rule.ops:
                continue
            touched_fields.add(rule.field)
            resolved, op_issues = apply_ops(self.engine, value, rule.ops)
            for issue in op_issues:
                self._append_issue(errors, warnings, rule, source, issue)
            normalized_values[rule.field] = resolved

        if self.sink_spec is not None:
            if self.options.validate_only_touched_fields:
                issues = validate_sink_fields(
                    normalized_values,
                    self.sink_spec,
                    fields=touched_fields,
                    check_types=True,
                )
            else:
                issues = validate_sink_row(normalized_values, self.sink_spec, check_types=True)
            for issue in issues:
                self._append_issue(
                    errors,
                    warnings,
                    rule=None,
                    source=source,
                    issue=issue,
                    on_error=self.spec.normalize.on_error,
                )

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
        rule: NormalizeRule | None,
        source: TransformResult[Any],
        issue: DslIssue,
        on_error: str | None = None,
    ) -> None:
        effective_on_error = on_error if on_error is not None else (rule.on_error if rule else "error")
        append_dsl_issue(
            errors=errors,
            warnings=warnings,
            stage=DiagnosticStage.NORMALIZE,
            issue=issue,
            catalog=self.catalog,
            record_ref=source.row_ref,
            on_error=effective_on_error,
        )
