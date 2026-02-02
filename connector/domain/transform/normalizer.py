from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.result import TransformResult

T = TypeVar("T")
U = TypeVar("U")

NormalizerParser = Callable[[Any, Callable[..., DiagnosticItem], Callable[..., DiagnosticItem]], Any]
NormalizerValidator = Callable[[Any, Callable[..., DiagnosticItem], Callable[..., DiagnosticItem]], None]


@dataclass(frozen=True)
class NormalizerRule:
    """
    Назначение:
        Декларативное правило нормализации одного поля.
    """

    target: str
    source_key: str
    parser: NormalizerParser | None = None
    validators: tuple[NormalizerValidator, ...] = ()
    required: bool = False

    def apply(
        self,
        values: dict[str, Any],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        record_ref,
        add_error: Callable[..., DiagnosticItem],
        add_warning: Callable[..., DiagnosticItem],
    ) -> Any:
        raw = values.get(self.source_key)
        if raw is None:
            if self.required:
                errors.append(
                    add_error(
                        code="REQUIRED_FIELD_MISSING",
                        field=self.source_key,
                        message=f"{self.source_key} is required",
                    )
                )
            return None
        parsed = raw
        if self.parser:
            parsed = self.parser(raw, add_error, add_warning)
        for validator in self.validators:
            validator(parsed, add_error, add_warning)
        return parsed


class NormalizerSpec(Generic[T]):
    """
    Назначение:
        Контракт набора правил нормализации для датасета.
    """

    rules: tuple[NormalizerRule, ...]

    def build_row(self, values: dict[str, Any]) -> T: ...


class Normalizer(Generic[T]):
    """
    Назначение:
        Ядро нормализатора: применяет правила и строит нормализованную строку.
    """

    def __init__(self, spec: NormalizerSpec[T], catalog: ErrorCatalog) -> None:
        self.spec = spec
        self.catalog = catalog

    def normalize(self, source: TransformResult[Any]) -> TransformResult[T]:
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []
        normalized_values: dict[str, Any] = {}

        collector = TransformResult(
            record=source.record,
            row=None,
            row_ref=source.row_ref,
            match_key=source.match_key,
            meta=source.meta,
            secret_candidates=source.secret_candidates,
        )

        def add_error(
            code: str,
            message: str | None = None,
            field: str | None = None,
            details: dict[str, Any] | None = None,
        ) -> DiagnosticItem:
            item = collector.add_error(
                catalog=self.catalog,
                stage=DiagnosticStage.NORMALIZE,
                code=code,
                field=field,
                message=message,
                details=details,
            )
            errors.append(item)
            return item

        def add_warning(
            code: str,
            message: str | None = None,
            field: str | None = None,
            details: dict[str, Any] | None = None,
        ) -> DiagnosticItem:
            item = collector.add_warning(
                catalog=self.catalog,
                stage=DiagnosticStage.NORMALIZE,
                code=code,
                field=field,
                message=message,
                details=details,
            )
            warnings.append(item)
            return item

        source_values = _to_mapping(source.row)
        if source_values is None:
            return TransformResult(
                record=source.record,
                row=None,
                row_ref=source.row_ref,
                match_key=source.match_key,
                meta=source.meta,
                secret_candidates=source.secret_candidates,
                errors=[*source.errors],
                warnings=[*source.warnings],
            )

        for rule in self.spec.rules:
            normalized_values[rule.target] = rule.apply(
                source_values,
                errors,
                warnings,
                source.row_ref,
                add_error,
                add_warning,
            )

        row = None
        if not errors:
            row = self.spec.build_row(normalized_values)
        return TransformResult(
            record=source.record,
            row=row,
            row_ref=source.row_ref,
            match_key=source.match_key,
            meta=source.meta,
            secret_candidates=source.secret_candidates,
            errors=[*source.errors, *errors],
            warnings=[*source.warnings, *warnings],
        )


def _to_mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    return value.__dict__
