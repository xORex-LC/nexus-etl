from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from connector.domain.models import Identity, ValidationRowResult

BuildIdentity = Callable[[Any, ValidationRowResult], Identity]
BuildLinks = Callable[[Any, ValidationRowResult], dict[str, Identity]]
BuildDesiredState = Callable[[Any, ValidationRowResult], dict[str, Any]]
BuildSourceRef = Callable[[Identity], dict[str, Any]]
DiffPolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]
SecretFieldsPolicy = Callable[[str, dict[str, Any], dict[str, Any] | None], list[str]]
MergePolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class MatchingRules:
    """
    Назначение:
        Набор правил сопоставления для matcher (dataset‑специфика).
    """

    build_identity: BuildIdentity
    ignored_fields: set[str] = field(default_factory=set)
    build_links: BuildLinks | None = None


@dataclass(frozen=True)
class ResolveRules:
    """
    Назначение:
        Набор правил разрешения для resolver (dataset‑специфика).

    Пояснения:
        merge_policy применяется до link-resolve и diff.
        Рекомендуемый контракт:
            - принимать existing и desired_state,
            - возвращать новый desired_state,
            - не удалять явно заданные значения,
            - использовать existing только как источник дефолтов.
        Важно:
            если merge_policy задан, оптимизация skip по fingerprint отключается.
    """

    build_desired_state: BuildDesiredState
    build_source_ref: BuildSourceRef | None = None
    diff_policy: DiffPolicy | None = None
    secret_fields_for_op: SecretFieldsPolicy | None = None
    merge_policy: MergePolicy | None = None


@dataclass(frozen=True)
class LinkKeyRule:
    """
    Назначение:
        Правило извлечения ключа для link-resolve.
    """

    name: str
    field: str


@dataclass(frozen=True)
class LinkFieldRule:
    """
    Назначение:
        Правило resolve для одного link-поля.
    """

    field: str
    target_dataset: str
    resolve_keys: tuple[LinkKeyRule, ...]
    dedup_rules: tuple[tuple[str, ...], ...] = ()
    target_id_field: str = "_id"
    coerce: str | None = None


@dataclass(frozen=True)
class LinkRules:
    """
    Назначение:
        Набор link-правил для resolver (dataset-специфика).
    """

    fields: tuple[LinkFieldRule, ...] = ()
