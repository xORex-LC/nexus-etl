"""Нормализация результата одной HTTP-попытки транспорта."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from connector.infra.target.transports.http.request_once import HttpOutcome


@dataclass(frozen=True, slots=True)
class HttpNormalizedOutcome:
    """Нормализованный результат одной HTTP-попытки."""

    status_code: int | None
    body: Any | None
    body_snippet: str | None
    error_code: str | None
    error_message: str | None
    retry_after_s: float | None


def _parse_retry_after(value: str | None) -> float | None:
    """Распарсить ``Retry-After`` (секунды или HTTP-date) в секунды ожидания."""
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


def _header_value_case_insensitive(headers: dict[str, str], name: str) -> str | None:
    """Прочитать значение заголовка без учёта регистра ключа."""
    lookup = name.strip().lower()
    for key, value in headers.items():
        if key.lower() == lookup:
            return value
    return None


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

    headers = outcome.response.headers
    retry_after_raw = _header_value_case_insensitive(headers, "Retry-After")
    retry_after_s = _parse_retry_after(retry_after_raw)
    return HttpNormalizedOutcome(
        status_code=outcome.response.status_code,
        body=outcome.response.body,
        body_snippet=outcome.response.body_snippet,
        error_code=None,
        error_message=None,
        retry_after_s=retry_after_s,
    )


__all__ = ["HttpNormalizedOutcome", "normalize_http_outcome"]
