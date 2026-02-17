from __future__ import annotations

from connector.infra.target.core.engines.safe_logging import TargetSafeLogger
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.providers.ankey_rest.provider import build_transport_compiler_registry
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec


def test_redact_headers_masks_sensitive_values() -> None:
    logger = TargetSafeLogger(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    redacted = logger.redact_headers({"Authorization": "Bearer secret", "Accept": "application/json"})

    assert redacted == {"Authorization": "***", "Accept": "application/json"}


def test_build_error_details_truncates_snippet_and_masks_body() -> None:
    logger = TargetSafeLogger(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    details = logger.build_error_details(
        payload={"user": "alice", "password": "secret"},
        content_preview="x" * 600,
    )

    assert details is not None
    assert details["response_payload"] == {"user": "alice", "password": "***"}
    snippet = details["content_preview"]
    assert isinstance(snippet, str)
    assert len(snippet) <= 500
    assert snippet.endswith("...")


def test_safe_body_truncates_raw_string() -> None:
    logger = TargetSafeLogger(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    value = logger.safe_body("x" * 600)

    assert isinstance(value, str)
    assert len(value) <= 500
    assert value.endswith("...")


def test_debug_retry_is_noop_safe() -> None:
    logger = TargetSafeLogger(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )
    logger.debug_retry(
        operation="execute",
        fault_kind="TRANSIENT",
        retries_used=1,
        max_retries=3,
        delay_s=0.1,
    )
