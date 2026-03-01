"""Purpose:
    Strategy-контракты для stage-specific поведения report adapter-а.

Boundary:
    - Определяет только разницу между transform/planning стадиями:
      skip policy, payload projection и meta projection.
    - Не содержит row aggregation и не пишет в collector напрямую.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from connector.domain.transform.core.result import TransformResult


class IStageReportStrategy(Protocol):
    """Purpose:
        Контракт strategy для StageResultReporter.
    """

    def should_skip(self, result: TransformResult | None) -> bool: ...

    def build_payload(self, result: TransformResult | None) -> Any: ...

    def build_meta(
        self,
        result: TransformResult | None,
        *,
        upstream_errors_count: int,
        upstream_warnings_count: int,
        secret_fields: list[str],
    ) -> dict[str, Any]: ...


class TransformStageReportStrategy:
    """Purpose:
        Стратегия для стандартных transform use-cases (normalize/mapping/enrich).
    """

    def __init__(self, payload_builder: Callable[[TransformResult], Any] | None = None) -> None:
        self._payload_builder = payload_builder

    def should_skip(self, result: TransformResult | None) -> bool:
        return False

    def build_payload(self, result: TransformResult | None) -> Any:
        if result is None or result.row is None:
            return None
        return self._payload_builder(result) if self._payload_builder else result.row

    def build_meta(
        self,
        result: TransformResult | None,
        *,
        upstream_errors_count: int,
        upstream_warnings_count: int,
        secret_fields: list[str],
    ) -> dict[str, Any]:
        return {
            "match_key": (result.match_key.value if result and result.match_key else None),
            "secret_candidate_fields": secret_fields,
            "upstream_errors_count": upstream_errors_count,
            "upstream_warnings_count": upstream_warnings_count,
        }


class PlanningStageReportStrategy:
    """Purpose:
        Стратегия для planning use-cases (match/resolve).

    Compatibility:
        Повторяет контракт legacy `PlanningResultProcessor` через callbacks
        `meta_builder` и `should_skip` на переходном окне совместимости.
    """

    def __init__(
        self,
        *,
        meta_builder: Callable[[TransformResult], dict[str, Any] | None],
        should_skip: Callable[[TransformResult], bool] | None = None,
        payload_builder: Callable[[TransformResult], Any] | None = None,
    ) -> None:
        self._meta_builder = meta_builder
        self._should_skip = should_skip
        self._payload_builder = payload_builder

    def should_skip(self, result: TransformResult | None) -> bool:
        if result is None or self._should_skip is None:
            return False
        return self._should_skip(result)

    def build_payload(self, result: TransformResult | None) -> Any:
        if result is None or result.row is None:
            return None
        return self._payload_builder(result) if self._payload_builder else result.row

    def build_meta(
        self,
        result: TransformResult | None,
        *,
        upstream_errors_count: int,
        upstream_warnings_count: int,
        secret_fields: list[str],
    ) -> dict[str, Any]:
        if result is None:
            meta: dict[str, Any] = {}
        else:
            meta = self._meta_builder(result) or {}
        meta.setdefault("upstream_errors_count", upstream_errors_count)
        meta.setdefault("upstream_warnings_count", upstream_warnings_count)
        return meta
