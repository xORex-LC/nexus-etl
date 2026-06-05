"""Observability value objects — component identity, naming policy and pure layout resolver.

Модуль хранит кросс-слойные value-objects для observability-подсистемы: логические компоненты
сервиса, policy-объекты и чистый layout resolver для путей логов/отчётов/планов. Здесь нет
I/O, DI wiring или привязки к конкретным infra-реализациям.

Границы ответственности:
    - Определять `ServiceComponent` как канонический ключ раскладки observability.
    - Предоставлять `ObservabilityLayout` как единственный источник имён runtime-артефактов.
    - Хранить value-only policy для layout/redaction.

Вне ответственности:
    - Создание директорий, открытие файлов, ротация и ретенция.
    - Загрузка конфигурации и lifecycle orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Literal, Protocol

from connector.common.sanitize import DEFAULT_SENSITIVE_FIELD_KEYS

ClockMode = Literal["utc", "local"]
LedgerBackendName = Literal["jsonl", "sqlite"]


class ServiceComponent(str, Enum):
    EXTRACTOR = "extractor"
    MAPPER = "mapper"
    NORMALIZER = "normalizer"
    ENRICHER = "enricher"
    MATCHER = "matcher"
    RESOLVER = "resolver"
    PLANNER = "planner"
    APPLIER = "applier"
    CACHE = "cache"
    VAULT = "vault"
    TOPOLOGY = "topology"
    OBSERVABILITY = "observability"


class ObservabilityArtifactKind(str, Enum):
    LOG = "log"
    REPORT = "report"
    PLAN = "plan"


@dataclass(frozen=True)
class ComponentIdentity:
    component: ServiceComponent


@dataclass(frozen=True)
class ObservabilityLayoutPolicy:
    partition_by_component: bool = True
    clock: ClockMode = "utc"


@dataclass(frozen=True)
class ObservabilityRedactionPolicy:
    enabled: bool = True
    keys: tuple[str, ...] = DEFAULT_SENSITIVE_FIELD_KEYS


class RuntimePathsLike(Protocol):
    @property
    def logs_root(self) -> Path: ...

    @property
    def reports_root(self) -> Path: ...

    @property
    def plans_root(self) -> Path: ...


@dataclass(frozen=True)
class ObservabilityLayout:
    """Чистый резолвер путей observability-артефактов.

    Layout зависит только от runtime roots, policy и момента времени. Методы возвращают `Path`
    и не создают директории, не открывают файлы и не трогают файловую систему.
    """

    runtime_paths: RuntimePathsLike
    policy: ObservabilityLayoutPolicy = ObservabilityLayoutPolicy()
    clock: Callable[[], datetime] | None = None

    def log_file(
        self,
        component: ServiceComponent | ComponentIdentity,
        *,
        now: datetime | None = None,
    ) -> Path:
        resolved_component = _coerce_component(component)
        resolved_now = self._resolve_now(now)
        directory = self._component_dir(
            self.runtime_paths.logs_root, resolved_component
        )
        filename = f"{resolved_now:%Y-%m-%d}_{resolved_component.value}.log"
        return directory / filename

    def report_file(
        self,
        component: ServiceComponent | ComponentIdentity,
        *,
        now: datetime | None = None,
    ) -> Path:
        resolved_component = _coerce_component(component)
        resolved_now = self._resolve_now(now)
        directory = self._component_dir(
            self.runtime_paths.reports_root, resolved_component
        )
        filename = f"{resolved_now:%Y-%m-%dT%H-%M-%S}_{resolved_component.value}.json"
        return directory / filename

    def plan_file(
        self,
        component: ServiceComponent | ComponentIdentity,
        *,
        now: datetime | None = None,
    ) -> Path:
        resolved_component = _coerce_component(component)
        resolved_now = self._resolve_now(now)
        directory = self._component_dir(
            self.runtime_paths.plans_root, resolved_component
        )
        filename = f"{resolved_now:%Y-%m-%dT%H-%M-%S}_{resolved_component.value}.json"
        return directory / filename

    def ledger_file(
        self,
        component: ServiceComponent | ComponentIdentity,
        *,
        backend: LedgerBackendName,
    ) -> Path:
        """Разрешить canonical ledger-файл компонента для выбранного backend.

        Ledger хранится рядом с логами компонента и не зависит от времени запуска:
        один индекс обслуживает всю историю запусков компонента.
        """
        resolved_component = _coerce_component(component)
        directory = self._component_dir(
            self.runtime_paths.logs_root, resolved_component
        )
        suffix = ".jsonl" if backend == "jsonl" else ".sqlite3"
        return directory / f"index{suffix}"

    def _resolve_now(self, now: datetime | None) -> datetime:
        current = now if now is not None else self._clock()()
        if self.policy.clock == "utc":
            if current.tzinfo is None:
                return current.replace(tzinfo=timezone.utc)
            return current.astimezone(timezone.utc)
        if current.tzinfo is None:
            return current
        return current.astimezone()

    def _clock(self) -> Callable[[], datetime]:
        if self.clock is not None:
            return self.clock
        if self.policy.clock == "utc":
            return lambda: datetime.now(timezone.utc)
        return lambda: datetime.now().astimezone()

    def _component_dir(self, root: Path, component: ServiceComponent) -> Path:
        if not self.policy.partition_by_component:
            return root
        return root / component.value


def _coerce_component(
    component: ServiceComponent | ComponentIdentity,
) -> ServiceComponent:
    if isinstance(component, ComponentIdentity):
        return component.component
    return component


__all__ = [
    "ClockMode",
    "ComponentIdentity",
    "LedgerBackendName",
    "ObservabilityArtifactKind",
    "ObservabilityLayout",
    "ObservabilityLayoutPolicy",
    "ObservabilityRedactionPolicy",
    "ServiceComponent",
]
