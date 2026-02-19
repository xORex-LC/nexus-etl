"""
Назначение:
    ResolveDsl: компиляция ResolveSpec в CompiledResolveRules.
    Compiled models: ResolveRules, LinkRules, LinkFieldRule, LinkKeyRule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from connector.domain.models import Identity
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.common import normalize_text
from connector.domain.dsl.issues import DslLoadError
from connector.domain.transform_dsl.build_options import ResolveDslBuildOptions
from connector.domain.transform_dsl.specs import (
    ResolveDiffFieldSpec,
    ResolveDiffSpec,
    ResolveLinkSpec,
    ResolveMergeSpec,
    ResolveSecretsSpec,
    ResolveSourceRefSpec,
    ResolveSpec,
    SinkSpec,
)

BuildDesiredState = Callable[[Any, MatchContext], dict[str, Any]]
BuildSourceRef = Callable[[Identity], dict[str, Any]]
DiffPolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]
SecretFieldsPolicy = Callable[[str, dict[str, Any], dict[str, Any] | None], list[str]]
MergePolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]


# ========== COMPILED MODELS ==========


@dataclass(frozen=True)
class ResolveRules:
    """
    Назначение:
        Набор правил разрешения для resolver (dataset‑специфика).
    """

    build_desired_state: BuildDesiredState
    build_source_ref: BuildSourceRef | None = None
    diff_policy: DiffPolicy | None = None
    secret_fields_for_op: SecretFieldsPolicy | None = None
    secret_lifecycle: "SecretLifecyclePolicy" | None = None
    merge_policy: MergePolicy | None = None


@dataclass(frozen=True)
class SecretLifecyclePolicy:
    """
    Назначение:
        Runtime-конфигурация retention policy для apply cleanup.

    Поля:
        mode: persistent/ephemeral.
        delete_on_success: удалять ли секреты после успешного apply-op.
        ttl_seconds: опциональный TTL для maintenance hooks.
    """

    mode: str = "persistent"
    delete_on_success: bool = False
    ttl_seconds: int | None = None


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
    on_unresolved: str = "pending"


@dataclass(frozen=True)
class LinkRules:
    """
    Назначение:
        Набор link-правил для resolver (dataset-специфика).
    """

    fields: tuple[LinkFieldRule, ...] = ()


@dataclass(frozen=True)
class CompiledResolveRules:
    """
    Назначение:
        Результат компиляции ResolveSpec в runtime-контракты.
    """

    resolve_rules: ResolveRules
    link_rules: LinkRules


# ========== COMPILER ==========


class ResolveDsl:
    """
    Назначение/ответственность:
        Компилирует ResolveSpec в ResolveRules/LinkRules без изменения resolver-core.
    """

    def __init__(self, *, options: ResolveDslBuildOptions | None = None) -> None:
        self.options = options or ResolveDslBuildOptions()

    def compile(
        self,
        spec: ResolveSpec,
        *,
        sink_spec: SinkSpec | None = None,
    ) -> CompiledResolveRules:
        """
        Назначение:
            Скомпилировать ResolveSpec в ResolveRules/LinkRules.
        """
        try:
            if not self.options.allow_pending_links:
                pending_links = [item.field for item in spec.resolve.links if item.on_unresolved == "pending"]
                if pending_links:
                    raise DslLoadError(
                        code="RESOLVE_DSL_COMPILE_INVALID",
                        message=(
                            "resolve links with on_unresolved='pending' are disabled by build options: "
                            + ", ".join(pending_links)
                        ),
                    )
            link_rules = LinkRules(
                fields=tuple(self._compile_link_rule(item) for item in spec.resolve.links),
            )
            resolve_rules = self._compile_v2(spec, sink_spec=sink_spec)
            return CompiledResolveRules(resolve_rules=resolve_rules, link_rules=link_rules)
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="RESOLVE_DSL_COMPILE_INVALID",
                message=f"Failed to compile resolve DSL: {exc}",
            ) from exc

    def _compile_v2(
        self,
        spec: ResolveSpec,
        *,
        sink_spec: SinkSpec | None,
    ) -> ResolveRules:
        block = spec.resolve
        desired_spec = block.desired_state
        diff_spec = block.diff
        if desired_spec is None or diff_spec is None:
            raise DslLoadError(
                code="RESOLVE_DSL_COMPILE_INVALID",
                message="resolve.desired_state and resolve.diff are required for Resolve DSL v2",
            )

        return ResolveRules(
            build_desired_state=self._compile_desired_state(desired_spec.fields, desired_spec.drop_fields),
            build_source_ref=self._compile_source_ref(block.source_ref),
            diff_policy=self._compile_diff(diff_spec, sink_spec=sink_spec),
            merge_policy=self._compile_merge(block.merge),
            secret_fields_for_op=self._compile_secret_fields(block.secrets),
            secret_lifecycle=self._compile_secret_lifecycle(block.secrets),
        )

    @staticmethod
    def _compile_desired_state(
        fields: list[str],
        drop_fields: list[str],
    ) -> BuildDesiredState:
        result_fields = tuple(fields)
        drop = set(drop_fields)

        def _builder(row: Any, _context: Any) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for name in result_fields:
                result[name] = _extract_value(row, name)
            for name in drop:
                result.pop(name, None)
            return result

        return _builder

    @staticmethod
    def _compile_source_ref(spec: ResolveSourceRefSpec | None) -> BuildSourceRef | None:
        if spec is None:
            return None
        fields = tuple(spec.fields)
        include_primary = spec.include_primary

        def _builder(identity) -> dict[str, Any]:
            source_ref: dict[str, Any] = {}
            if not fields:
                if include_primary and identity.primary_value is not None:
                    source_ref[identity.primary] = identity.primary_value
                return source_ref

            for name in fields:
                value = identity.values.get(name)
                if value in (None, "") and include_primary and name == identity.primary:
                    value = identity.primary_value
                if value in (None, ""):
                    continue
                source_ref[name] = value

            if include_primary and identity.primary not in source_ref and identity.primary_value is not None:
                source_ref[identity.primary] = identity.primary_value
            return source_ref

        return _builder

    @staticmethod
    def _compile_diff(
        spec: ResolveDiffSpec,
        *,
        sink_spec: SinkSpec | None,
    ) -> DiffPolicy:
        rules = tuple(_build_diff_rules(spec, sink_spec=sink_spec))
        ignored = set(spec.ignore_fields)

        def _diff(existing: dict[str, Any] | None, desired_state: dict[str, Any]) -> dict[str, Any]:
            if not existing:
                return {}
            changes: dict[str, Any] = {}
            for rule in rules:
                if rule.field in ignored:
                    continue
                existing_key = rule.existing or rule.field
                output_key = rule.output or rule.field
                desired_value = _normalize_for_mode(desired_state.get(rule.field), rule.normalize)
                existing_value = _normalize_for_mode(existing.get(existing_key), rule.normalize)
                if existing_value != desired_value:
                    changes[output_key] = desired_value
            return changes

        return _diff

    @staticmethod
    def _compile_merge(spec: ResolveMergeSpec | None) -> MergePolicy | None:
        if spec is None or spec.mode == "none":
            return None
        rules = tuple(spec.fields)

        def _merge(existing: dict[str, Any] | None, desired_state: dict[str, Any]) -> dict[str, Any]:
            if not existing:
                return dict(desired_state)
            merged = dict(desired_state)
            for rule in rules:
                current = merged.get(rule.field)
                if current not in (None, ""):
                    continue
                existing_key = rule.existing or rule.field
                fallback = _normalize_for_mode(existing.get(existing_key), rule.normalize)
                if fallback in (None, ""):
                    continue
                merged[rule.field] = fallback
            return merged

        return _merge

    @staticmethod
    def _compile_secret_fields(spec: ResolveSecretsSpec | None) -> SecretFieldsPolicy | None:
        if spec is None or spec.mode == "none":
            return None
        create_fields = tuple(spec.create)
        update_fields = tuple(spec.update)

        def _policy(op: str, desired_state: dict[str, Any], existing: dict[str, Any] | None) -> list[str]:
            _ = (desired_state, existing)
            if op == "create":
                return list(create_fields)
            if op == "update":
                return list(update_fields)
            return []

        return _policy

    @staticmethod
    def _compile_secret_lifecycle(spec: ResolveSecretsSpec | None) -> SecretLifecyclePolicy:
        """
        Назначение:
            Скомпилировать lifecycle policy для retention в apply-runtime.

        Контракт:
            - default: `persistent` + no delete-on-success;
            - `ephemeral` по умолчанию включает delete-on-success.
        """
        if spec is None or spec.lifecycle is None:
            return SecretLifecyclePolicy(mode="persistent", delete_on_success=False, ttl_seconds=None)

        lifecycle = spec.lifecycle
        mode = lifecycle.mode
        delete_on_success = (
            bool(lifecycle.delete_on_success)
            if lifecycle.delete_on_success is not None
            else mode == "ephemeral"
        )
        return SecretLifecyclePolicy(
            mode=mode,
            delete_on_success=delete_on_success,
            ttl_seconds=lifecycle.ttl_seconds,
        )

    @staticmethod
    def _compile_link_rule(spec: ResolveLinkSpec) -> LinkFieldRule:
        return LinkFieldRule(
            field=spec.field,
            target_dataset=spec.target_dataset,
            resolve_keys=tuple(LinkKeyRule(name=item.name, field=item.field) for item in spec.resolve_keys),
            dedup_rules=tuple(tuple(rule) for rule in spec.dedup_rules),
            target_id_field=spec.target_id_field,
            coerce=spec.coerce,
            on_unresolved=spec.on_unresolved,
        )


# ========== PRIVATE HELPERS ==========


def _extract_value(payload: Any, field_name: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(field_name)
    return getattr(payload, field_name, None)


def _normalize_for_mode(value: Any, mode: str) -> Any:
    if mode == "none":
        return value
    if mode == "text":
        return normalize_text(value, empty_to_none=False)
    if mode == "bool":
        return _to_bool(value)
    return value


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "y"):
            return True
        if normalized in ("0", "false", "no", "n"):
            return False
    return None


def _build_diff_rules(
    spec: ResolveDiffSpec,
    *,
    sink_spec: SinkSpec | None,
) -> list[ResolveDiffFieldSpec]:
    if not spec.from_sink.enabled:
        return list(spec.fields)
    if sink_spec is None:
        raise DslLoadError(
            code="RESOLVE_DSL_COMPILE_INVALID",
            message="resolve.diff.from_sink.enabled=true requires sink_spec for ResolveDsl.compile()",
        )

    excluded = set(spec.from_sink.exclude_fields)
    rules: list[ResolveDiffFieldSpec] = []
    field_pos: dict[str, int] = {}

    for sink_field in sink_spec.sink.fields:
        name = sink_field.name
        if name in excluded:
            continue
        normalize = "none"
        if spec.from_sink.normalize_by_type:
            if sink_field.type == "string":
                normalize = "text"
            elif sink_field.type == "bool":
                normalize = "bool"
        rule = ResolveDiffFieldSpec(
            field=name,
            normalize=normalize,
        )
        field_pos[name] = len(rules)
        rules.append(rule)

    for override in spec.fields:
        idx = field_pos.get(override.field)
        if idx is None:
            field_pos[override.field] = len(rules)
            rules.append(override)
        else:
            rules[idx] = override

    return rules
