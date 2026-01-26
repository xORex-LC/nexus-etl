from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.ports.secrets import SecretStoreProtocol
from connector.domain.transform.result import TransformResult

T = TypeVar("T")
D = TypeVar("D")


class EnrichRule(Protocol, Generic[T, D]):
    """
    Назначение:
        Контракт правила обогащения.
    """

    name: str

    def apply(
        self,
        result: TransformResult[T],
        deps: D,
        errors: list[ValidationErrorItem],
        warnings: list[ValidationErrorItem],
    ) -> None: ...


@dataclass(frozen=True)
class EnricherSpec(Generic[T, D]):
    """
    Назначение:
        Набор правил обогащения для датасета.
    """

    rules: tuple[EnrichRule[T, D], ...]


class Enricher(Generic[T, D]):
    """
    Назначение:
        Ядро обогащения: применяет правила и сохраняет секреты.
    """

    def __init__(
        self,
        spec: EnricherSpec[T, D],
        deps: D,
        secret_store: SecretStoreProtocol | None,
        dataset: str,
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.deps = deps
        self.secret_store = secret_store
        self.dataset = dataset
        self.run_id = run_id

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
        if result.errors:
            return result
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        for rule in self.spec.rules:
            rule.apply(result, self.deps, errors, warnings)

        if errors:
            result.errors = [*result.errors, *errors]
            result.warnings = [*result.warnings, *warnings]
            return result

        if result.secret_candidates and self.secret_store is not None:
            if result.match_key is None:
                errors.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.ENRICH,
                        code="MATCH_KEY_MISSING",
                        field="matchKey",
                        message="match_key is required to store secrets",
                    )
                )
            else:
                try:
                    self.secret_store.put_many(
                        dataset=self.dataset,
                        match_key=result.match_key.value,
                        secrets=result.secret_candidates,
                        run_id=self.run_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        ValidationErrorItem(
                            stage=DiagnosticStage.ENRICH,
                            code="SECRET_STORE_ERROR",
                            field=None,
                            message=str(exc),
                        )
                    )

        result.errors = [*result.errors, *errors]
        result.warnings = [*result.warnings, *warnings]
        return result
