"""
Назначение:
    NormalizerDsl: компиляция NormalizeSpec в CompiledNormalizeRules.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.transform_dsl.build_options import NormalizeDslBuildOptions
from connector.domain.transform_dsl.specs import NormalizeRule, NormalizeSpec


@dataclass(frozen=True)
class CompiledNormalizeRules:
    """
    Назначение:
        Скомпилированные normalize-правила (frozen, data-only).
    """

    rules: tuple[NormalizeRule, ...]
    on_error: str
    options: NormalizeDslBuildOptions


class NormalizerDsl:
    """
    Назначение/ответственность:
        Преобразует DSL-спеку нормализации в CompiledNormalizeRules.
    """

    def __init__(
        self,
        *,
        registry: OperationRegistry | None = None,
        engine: TransformationEngine | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine
        self.options = options or NormalizeDslBuildOptions()

    def compile(self, spec: NormalizeSpec) -> CompiledNormalizeRules:
        """
        Назначение:
            Скомпилировать NormalizeSpec в CompiledNormalizeRules.
        """
        if self.options.fail_on_unknown_ops:
            self._validate_ops_known(spec)
        try:
            return CompiledNormalizeRules(
                rules=tuple(spec.normalize.rules),
                on_error=spec.normalize.on_error,
                options=self.options,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="NORMALIZE_DSL_COMPILE_INVALID",
                message=f"Failed to compile normalize DSL: {exc}",
            ) from exc

    def _validate_ops_known(self, spec: NormalizeSpec) -> None:
        for rule in spec.normalize.rules:
            for op_call in rule.ops:
                if self.engine.registry.get(op_call.op) is None:
                    raise DslLoadError(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}' in normalize rule for field '{rule.field}'",
                        details={"op": op_call.op, "dataset": spec.dataset},
                    )
