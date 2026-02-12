"""
Назначение:
    NormalizerDsl: компиляция NormalizeSpec в NormalizerCore.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.dsl.build_options import NormalizeDslBuildOptions
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.dsl.specs import NormalizeSpec, SinkSpec
from connector.domain.transform.normalize.normalizer_core import NormalizerCore, RowBuilder


class NormalizerDsl:
    """
    Назначение/ответственность:
        Преобразует DSL-спеку нормализации в NormalizerCore.
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

    def compile(
        self,
        spec: NormalizeSpec,
        *,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder | None = None,
    ) -> NormalizerCore:
        """
        Назначение:
            Скомпилировать NormalizeSpec в NormalizerCore.
        """
        if self.options.fail_on_unknown_ops:
            self._validate_ops_known(spec)
        try:
            return NormalizerCore(
                spec,
                engine=self.engine,
                catalog=catalog,
                sink_spec=sink_spec,
                row_builder=row_builder,
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
