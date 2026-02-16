"""Нормализация результата одной HTTP-попытки транспорта."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from connector.infra.target.transports.http.request_once import HttpOutcome


@dataclass(frozen=True, slots=True)
class HttpNormalizedOutcome:
    status_code: int | None
    body: Any | None
    body_snippet: str | None
    error_code: str | None
    error_message: str | None
    retry_after_s: float | None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate == "":
        return None
    try:
        seconds = float(candidate)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(candidate)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return delta if delta > 0 else 0.0


def normalize_http_outcome(outcome: HttpOutcome) -> HttpNormalizedOutcome:
    """Преобразовать транспортный результат в стабильный нормализованный DTO."""
    if outcome.error is not None:
        return HttpNormalizedOutcome(
            status_code=None,
            body=None,
            body_snippet=None,
            error_code=outcome.error.code,
            error_message=outcome.error.message,
            retry_after_s=None,
        )
    if outcome.response is None:
        return HttpNormalizedOutcome(
            status_code=None,
            body=None,
            body_snippet=None,
            error_code="HTTP_OUTCOME_EMPTY",
            error_message="empty http outcome",
            retry_after_s=None,
        )

    retry_after_s = _parse_retry_after(outcome.response.headers.get("Retry-After"))
    return HttpNormalizedOutcome(
        status_code=outcome.response.status_code,
        body=outcome.response.body,
        body_snippet=outcome.response.body_snippet,
        error_code=None,
        error_message=None,
        retry_after_s=retry_after_s,
    )


__all__ = ["HttpNormalizedOutcome", "normalize_http_outcome"]
