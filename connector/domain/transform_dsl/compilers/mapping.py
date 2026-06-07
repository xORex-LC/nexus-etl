"""
Назначение:
    MapperDsl: компиляция MappingSpec в CompiledMapRules.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.transform_dsl.build_options import MapDslBuildOptions
from connector.domain.transform_dsl.specs import (
    MappingRule,
    MappingSchema,
    MappingSpec,
    MetaRule,
    SinkSpec,
)


@dataclass(frozen=True)
class CompiledMapRules:
    """
    Назначение:
        Скомпилированные mapping-правила (frozen, data-only).
    """

    rules: tuple[MappingRule, ...]
    meta: tuple[MetaRule, ...]
    schema_: MappingSchema | None
    source_columns: tuple[str, ...] | None
    options: MapDslBuildOptions


class MapperDsl:
    """
    Назначение/ответственность:
        Преобразует DSL-спеку маппинга в CompiledMapRules.
    """

    def __init__(
        self,
        *,
        registry: OperationRegistry | None = None,
        engine: TransformationEngine | None = None,
        options: MapDslBuildOptions | None = None,
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine
        self.options = options or MapDslBuildOptions()

    def compile(
        self, spec: MappingSpec, *, sink_spec: SinkSpec | None = None
    ) -> CompiledMapRules:
        """
        Назначение:
            Скомпилировать MappingSpec в CompiledMapRules.
        """
        if self.options.require_targets_exist_in_sink_spec and sink_spec is None:
            raise DslLoadError(
                code="MAP_DSL_COMPILE_INVALID",
                message="sink_spec is required when require_targets_exist_in_sink_spec=true",
                details={"dataset": spec.dataset},
            )
        if self.options.require_targets_exist_in_sink_spec and sink_spec is not None:
            self._validate_targets_in_sink(spec, sink_spec)
        if self.options.fail_on_unknown_ops:
            self._validate_ops_known(spec)
        try:
            return CompiledMapRules(
                rules=tuple(spec.mapping.rules),
                meta=tuple(spec.mapping.meta),
                schema_=spec.mapping.schema_,
                source_columns=tuple(spec.source_columns)
                if spec.source_columns
                else None,
                options=self.options,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="MAP_DSL_COMPILE_INVALID",
                message=f"Failed to compile mapping DSL: {exc}",
            ) from exc

    def _validate_targets_in_sink(self, spec: MappingSpec, sink_spec: SinkSpec) -> None:
        sink_fields = {f.name for f in sink_spec.sink.fields} | {
            f.name for f in sink_spec.sink.system_fields
        }
        for rule in spec.mapping.rules:
            targets = rule.targets or ([rule.target] if rule.target else [])
            for target in targets:
                if target not in sink_fields:
                    raise DslLoadError(
                        code="MAP_DSL_COMPILE_INVALID",
                        message=f"Mapping target '{target}' does not exist in sink spec",
                        details={"target": target, "dataset": spec.dataset},
                    )

    def _validate_ops_known(self, spec: MappingSpec) -> None:
        for rule in spec.mapping.rules:
            for op_call in rule.ops:
                if self.engine.registry.get(op_call.op) is None:
                    raise DslLoadError(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}' in mapping rule for target '{rule.target or rule.targets}'",
                        details={"op": op_call.op, "dataset": spec.dataset},
                    )
        for rule in spec.mapping.meta:
            for op_call in rule.ops:
                if self.engine.registry.get(op_call.op) is None:
                    raise DslLoadError(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}' in mapping meta rule for target '{rule.target}'",
                        details={"op": op_call.op, "dataset": spec.dataset},
                    )
