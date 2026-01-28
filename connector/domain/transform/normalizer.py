from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Generic, Mapping, TypeVar

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.transform.result import TransformResult

T = TypeVar("T")
U = TypeVar("U")

NormalizerParser = Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], Any]
NormalizerValidator = Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], None]


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

    def apply(self, values: dict[str, Any], errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> Any:
        raw = values.get(self.source_key)
        if raw is None:
            if self.required:
                errors.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.NORMALIZE,
                        code="REQUIRED_FIELD_MISSING",
                        field=self.source_key,
                        message=f"{self.source_key} is required",
                    )
                )
            return None
        parsed = raw
        if self.parser:
            parsed = self.parser(raw, errors, warnings)
        for validator in self.validators:
            validator(parsed, errors, warnings)
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

    def __init__(self, spec: NormalizerSpec[T]) -> None:
        self.spec = spec

    def normalize(self, source: TransformResult[Any]) -> TransformResult[T]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        normalized_values: dict[str, Any] = {}

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
            normalized_values[rule.target] = rule.apply(source_values, errors, warnings)

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
