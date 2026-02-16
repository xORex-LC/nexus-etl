"""
TargetSpec — декларативная спецификация target-системы.

Назначение:
    Декларативное описание target: возможности, проверка доступности, пагинация,
    правила классификации ошибок (`fault_rules`), retry-политики (`retry_rules`),
    правила безопасного логирования (`redaction`), каталог operation aliases.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from connector.infra.target.core.models import TargetFaultKind

TargetCapability = Literal["check", "execute", "read_paged"]
RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]


class _SpecModel(BaseModel):
    """Базовая модель spec-слоя: неизменяемая и строгая."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class HealthCheckSpec(_SpecModel):
    """Описание операции health-check."""

    path: str
    params: dict[str, str] = Field(default_factory=dict)
    expected_status: int = 200


class PagingSpec(_SpecModel):
    """Стратегия пагинации target."""

    strategy: Literal["offset_limit", "cursor"] = "offset_limit"
    page_param: str = "page"
    size_param: str = "rows"
    filter_param: str = "_queryFilter"
    filter_value: str = "true"


class FaultRule(_SpecModel):
    """Правило классификации: HTTP статус / error code -> FaultKind."""

    fault_kind: TargetFaultKind
    match_status: int | None = None
    match_status_range: tuple[int, int] | None = None
    match_error_code: str | None = None

    @model_validator(mode="after")
    def _validate_matcher(self) -> "FaultRule":
        has_matcher = (
            self.match_status is not None
            or self.match_status_range is not None
            or self.match_error_code is not None
        )
        if not has_matcher:
            raise ValueError("fault rule requires match_status, match_status_range or match_error_code")
        if self.match_status is not None and self.match_status_range is not None:
            raise ValueError("fault rule cannot define both match_status and match_status_range")
        if self.match_status_range is not None:
            low, high = self.match_status_range
            if low > high:
                raise ValueError("fault rule status range must be ordered")
        return self


class RetryRule(_SpecModel):
    """Правило реакции: FaultKind / статус -> RetryDirective."""

    directive: RetryDirective
    match_fault: TargetFaultKind | None = None
    match_status: int | None = None

    @model_validator(mode="after")
    def _validate_matcher(self) -> "RetryRule":
        if self.match_fault is None and self.match_status is None:
            raise ValueError("retry rule requires match_fault or match_status")
        return self


class RetryConfig(_SpecModel):
    """Параметры механики retry (backoff, jitter, лимиты)."""

    # `max_attempts` — число повторов (не включая базовую первую попытку).
    max_attempts: int = Field(default=3, ge=0)
    backoff_base: float = Field(default=0.5, ge=0.0)
    backoff_max: float = Field(default=30.0, ge=0.0)
    jitter: bool = True

    @model_validator(mode="after")
    def _validate_backoff(self) -> "RetryConfig":
        if self.backoff_max < self.backoff_base:
            raise ValueError("backoff_max must be greater or equal to backoff_base")
        return self


class HttpOperationData(_SpecModel):
    """HTTP-часть декларации alias-операции target."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    query_defaults: dict[str, Any] = Field(default_factory=dict)
    header_defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_path_template(self) -> "HttpOperationData":
        if not self.path_template.startswith("/"):
            raise ValueError("path_template must start with '/'")
        return self


class OperationSpec(_SpecModel):
    """Декларация target-операции, разрешаемой по alias."""

    alias: str
    kind: Literal["http"] = "http"
    expected_statuses: tuple[int, ...] = (200,)
    timeout_ms: int | None = Field(default=None, ge=1)
    retry_profile: str | None = None
    redaction_override: dict[str, Any] | None = None
    http: HttpOperationData | None = None

    @model_validator(mode="after")
    def _validate_operation(self) -> "OperationSpec":
        alias = self.alias.strip()
        if alias == "":
            raise ValueError("operation alias must not be empty")
        object.__setattr__(self, "alias", alias)
        if self.kind == "http" and self.http is None:
            raise ValueError("http operation requires http payload")
        if not self.expected_statuses:
            raise ValueError("operation expected_statuses must not be empty")
        return self


class RedactionSpec(_SpecModel):
    """Правила маскирования для безопасного логирования."""

    forbidden_headers: frozenset[str] = frozenset(
        {
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-ankey-password",
        }
    )
    forbidden_fields: frozenset[str] = frozenset(
        {
            "password",
            "token",
            "secret",
            "api_key",
        }
    )
    body_mode: Literal["none", "keys_only", "truncated"] = "truncated"


class TargetSpec(_SpecModel):
    """Полная спецификация target-системы."""

    target_type: str
    capabilities: frozenset[TargetCapability]
    health_check: HealthCheckSpec
    paging: PagingSpec
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    operations: dict[str, OperationSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_operations(self) -> "TargetSpec":
        for alias, operation in self.operations.items():
            if alias != operation.alias:
                raise ValueError(
                    f"operation alias key mismatch: key={alias!r}, alias={operation.alias!r}",
                )
        return self
