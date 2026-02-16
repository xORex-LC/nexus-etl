"""
Код-спецификация target для Ankey IDM.

Назначение:
    Декларативное описание Ankey API: эндпоинты, пагинация,
    правила классификации ошибок, retry-политики, redaction.
"""

from __future__ import annotations

from connector.infra.target.spec import (
    FaultRule,
    HealthCheckSpec,
    HttpOperationData,
    OperationSpec,
    PagingSpec,
    RedactionSpec,
    RetryConfig,
    RetryRule,
    TargetSpec,
)


def build_ankey_spec() -> TargetSpec:
    """Собрать TargetSpec для Ankey IDM API."""
    return TargetSpec(
        target_type="ankey",
        capabilities=frozenset({"check", "execute", "read_paged"}),
        health_check=HealthCheckSpec(
            path="/ankey/managed/user",
            params={"page": "1", "rows": "1", "_queryFilter": "true"},
        ),
        paging=PagingSpec(),
        fault_rules=(
            # Аутентификация / авторизация
            FaultRule(fault_kind="AUTH", match_status=401),
            FaultRule(fault_kind="PERMISSION", match_status=403),
            # Ошибки данных
            FaultRule(fault_kind="DATA", match_status=400),
            FaultRule(fault_kind="DATA", match_status=422),
            FaultRule(fault_kind="NOT_FOUND", match_status=404),
            FaultRule(fault_kind="CONFLICT", match_status=409),
            # Rate limit
            FaultRule(fault_kind="THROTTLE", match_status=429),
            # Transient (серверные + сетевые)
            FaultRule(fault_kind="TRANSIENT", match_status_range=(500, 599)),
            FaultRule(fault_kind="TRANSIENT", match_error_code="NETWORK_ERROR"),
        ),
        retry_rules=(
            RetryRule(directive="RETRY_BACKOFF", match_fault="TRANSIENT"),
            RetryRule(directive="RETRY_BACKOFF", match_fault="THROTTLE"),
            RetryRule(directive="NO_RETRY", match_fault="AUTH"),
            RetryRule(directive="NO_RETRY", match_fault="PERMISSION"),
            RetryRule(directive="NO_RETRY", match_fault="DATA"),
            RetryRule(directive="NO_RETRY", match_fault="NOT_FOUND"),
            RetryRule(directive="NO_RETRY", match_fault="CONFLICT"),
        ),
        retry_config=RetryConfig(),
        redaction=RedactionSpec(),
        operations={
            "health.check": OperationSpec(
                alias="health.check",
                expected_statuses=(200,),
                http=HttpOperationData(
                    method="GET",
                    path_template="/ankey/managed/user",
                    query_defaults={"page": "1", "rows": "1", "_queryFilter": "true"},
                ),
            ),
            "users.list": OperationSpec(
                alias="users.list",
                expected_statuses=(200,),
                http=HttpOperationData(
                    method="GET",
                    path_template="/ankey/managed/user",
                    query_defaults={"_queryFilter": "true"},
                ),
            ),
            "organizations.list": OperationSpec(
                alias="organizations.list",
                expected_statuses=(200,),
                http=HttpOperationData(
                    method="GET",
                    path_template="/ankey/managed/organization",
                    query_defaults={"_queryFilter": "true"},
                ),
            ),
            "users.upsert": OperationSpec(
                alias="users.upsert",
                expected_statuses=(200, 201),
                http=HttpOperationData(
                    method="PUT",
                    path_template="/ankey/managed/user/{target_id}",
                    query_defaults={"_prettyPrint": "true", "decrypt": "false"},
                ),
            ),
        },
    )
