"""
TargetSpec — декларативная спецификация target-системы.

Назначение:
    Data-driven описание target: capabilities, health-check, пагинация,
    правила классификации ошибок (fault_rules), retry-политики (retry_rules),
    правила безопасного логирования (redaction).

    На данном этапе spec задаётся кодом (см. spec_ankey.py).
    В будущем может загружаться из DSL/YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from connector.infra.target.models import TargetFaultKind

TargetCapability = Literal["check", "execute", "read_paged"]
RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]


@dataclass(frozen=True, slots=True)
class HealthCheckSpec:
    """Описание операции health-check."""

    path: str
    params: dict[str, str] = field(default_factory=dict)
    expected_status: int = 200


@dataclass(frozen=True, slots=True)
class PagingSpec:
    """Стратегия пагинации target."""

    strategy: Literal["offset_limit", "cursor"] = "offset_limit"
    page_param: str = "page"
    size_param: str = "rows"
    filter_param: str = "_queryFilter"
    filter_value: str = "true"


@dataclass(frozen=True, slots=True)
class FaultRule:
    """Правило классификации: HTTP status / error code → FaultKind."""

    fault_kind: TargetFaultKind
    match_status: int | None = None
    match_status_range: tuple[int, int] | None = None
    match_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RetryRule:
    """Правило реакции: FaultKind / status → RetryDirective."""

    directive: RetryDirective
    match_fault: TargetFaultKind | None = None
    match_status: int | None = None


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Параметры механики retry (backoff, jitter, лимиты)."""

    max_attempts: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 30.0
    jitter: bool = True


@dataclass(frozen=True, slots=True)
class HttpOperationData:
    """HTTP-часть декларации alias-операции target."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    query_defaults: dict[str, Any] = field(default_factory=dict)
    header_defaults: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Декларация target-операции, разрешаемой по alias."""

    alias: str
    kind: Literal["http"] = "http"
    expected_statuses: tuple[int, ...] = (200,)
    timeout_ms: int | None = None
    retry_profile: str | None = None
    redaction_override: dict[str, Any] | None = None
    http: HttpOperationData | None = None

    def __post_init__(self) -> None:
        if self.alias.strip() == "":
            raise ValueError("operation alias must not be empty")
        if self.kind == "http" and self.http is None:
            raise ValueError("http operation requires http payload")
        if not self.expected_statuses:
            raise ValueError("operation expected_statuses must not be empty")


@dataclass(frozen=True, slots=True)
class RedactionSpec:
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


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """Полная спецификация target-системы."""

    target_type: str
    capabilities: frozenset[TargetCapability]
    health_check: HealthCheckSpec
    paging: PagingSpec
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    operations: dict[str, OperationSpec] = field(default_factory=dict)
