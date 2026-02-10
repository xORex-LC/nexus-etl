"""
Назначение:
    Детерминированный расчет порядка выполнения cache-сценариев
    с учетом зависимостей датасетов.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Mapping, Sequence


class CacheDependencyGraph:
    """
    Чистая модель зависимостей cache-датасетов.
    """

    def __init__(
        self,
        datasets: Sequence[str],
        dependencies: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        ordered = tuple(dict.fromkeys(datasets))
        if not ordered:
            raise ValueError("CacheDependencyGraph requires at least one dataset")
        self._datasets = ordered

        raw_deps = dependencies or {}
        dep_map: dict[str, tuple[str, ...]] = {}
        for name in self._datasets:
            dep_map[name] = tuple(dict.fromkeys(raw_deps.get(name, ()) or ()))

        unknown: list[str] = []
        for name, deps in dep_map.items():
            for dep in deps:
                if dep not in self._datasets:
                    unknown.append(f"{name}->{dep}")
        if unknown:
            joined = ", ".join(unknown)
            raise ValueError(f"CacheDependencyGraph has unknown dependencies: {joined}")

        self._dependencies = dep_map
        self._dependents = _build_dependents(dep_map)
        self._topo = _topological_order(self._datasets, self._dependencies)

    @property
    def datasets(self) -> tuple[str, ...]:
        return self._datasets

    def refresh_order(self, dataset: str | None = None, *, include_dependencies: bool = False) -> list[str]:
        """
        Возвращает порядок refresh.
        По умолчанию сохраняет текущее поведение: только явный dataset без авто-подтягивания deps.
        """
        if dataset is None:
            return list(self._topo)
        self._ensure_dataset(dataset)
        if not include_dependencies:
            return [dataset]
        scope = {dataset}
        _expand_dependencies(scope, self._dependencies)
        return [name for name in self._topo if name in scope]

    def clear_order(self, dataset: str | None = None, *, cascade: bool = False) -> list[str]:
        """
        Возвращает порядок clear.
        По умолчанию сохраняет текущее поведение: all datasets в стандартном порядке.
        """
        if dataset is None:
            return list(self._topo)
        self._ensure_dataset(dataset)
        if not cascade:
            return [dataset]
        scope = {dataset}
        _expand_dependents(scope, self._dependents)
        return [name for name in reversed(self._topo) if name in scope]

    def _ensure_dataset(self, dataset: str) -> None:
        if dataset not in self._dependencies:
            raise ValueError(f"Unsupported cache dataset: {dataset}")


def _build_dependents(dep_map: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for dataset, deps in dep_map.items():
        for dep in deps:
            reverse[dep].append(dataset)
    return {name: tuple(values) for name, values in reverse.items()}


def _topological_order(
    datasets: Sequence[str],
    dep_map: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    indegree = {name: 0 for name in datasets}
    edges: dict[str, list[str]] = defaultdict(list)
    for name, deps in dep_map.items():
        for dep in deps:
            edges[dep].append(name)
            indegree[name] += 1

    queue = deque(name for name in datasets if indegree[name] == 0)
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for nxt in edges.get(current, ()):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(datasets):
        raise ValueError("CacheDependencyGraph contains dependency cycle")
    return tuple(ordered)


def _expand_dependencies(scope: set[str], dep_map: Mapping[str, Sequence[str]]) -> None:
    queue = deque(scope)
    while queue:
        current = queue.popleft()
        for dep in dep_map.get(current, ()):
            if dep not in scope:
                scope.add(dep)
                queue.append(dep)


def _expand_dependents(scope: set[str], dependents: Mapping[str, Sequence[str]]) -> None:
    queue = deque(scope)
    while queue:
        current = queue.popleft()
        for dep in dependents.get(current, ()):
            if dep not in scope:
                scope.add(dep)
                queue.append(dep)
