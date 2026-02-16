"""
Реестр mutate-операций target-core.

Назначение:
    Хранит mapping `mutation_name -> callable`, который может быть использован
    TargetGateway при retry-цикле перед следующей попыткой.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from connector.domain.ports.target.execution import RequestSpec

TargetMutation = Callable[[RequestSpec], RequestSpec]


class TargetMutationRegistry:
    """Реестр мутаций запроса по имени."""

    def __init__(self, mutations: Mapping[str, TargetMutation] | None = None) -> None:
        self._mutations: dict[str, TargetMutation] = dict(mutations or {})

    def register(self, name: str, mutation: TargetMutation) -> None:
        normalized = name.strip()
        if normalized == "":
            raise ValueError("mutation name must not be empty")
        if normalized in self._mutations:
            raise ValueError(f"mutation already registered: {normalized}")
        self._mutations[normalized] = mutation

    def apply(self, name: str, request_spec: RequestSpec) -> RequestSpec:
        mutation = self._mutations.get(name)
        if mutation is None:
            raise ValueError(f"unknown mutation: {name}")
        return mutation(request_spec)


__all__ = ["TargetMutation", "TargetMutationRegistry"]
