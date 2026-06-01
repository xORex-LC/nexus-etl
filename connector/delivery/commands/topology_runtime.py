"""Handler-scope topology runtime helpers.

Инкапсулирует способ, которым pre-handler bootstrap результат передаётся в
planning pipeline composition. Команды не знают деталей bootstrap use case-а и
не читают raw `ctx.extra` вручную; они просто открывают scoped override для
pipeline topology inputs перед materialization stages.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Iterator

from connector.delivery.cli.context import BoundCommandContext
from connector.usecases.topology_bootstrap import TopologyRuntimeBinding

_CTX_KEY = "topology_runtime"


def get_topology_runtime(ctx: BoundCommandContext) -> TopologyRuntimeBinding | None:
    """Извлечь pre-handler topology runtime binding из command context."""

    extra = ctx.extra or {}
    runtime = extra.get(_CTX_KEY)
    if runtime is None:
        return None
    if not isinstance(runtime, TopologyRuntimeBinding):
        raise TypeError(
            "ctx.extra['topology_runtime'] must be TopologyRuntimeBinding"
        )
    return runtime


@contextmanager
def pipeline_topology_scope(
    *,
    ctx: BoundCommandContext,
    pipeline,
) -> Iterator[None]:
    """Прокинуть topology provider в planning pipeline composition scope."""

    runtime = get_topology_runtime(ctx)
    if runtime is None:
        with nullcontext():
            yield
        return

    provider_override = nullcontext()
    requirements_override = nullcontext()
    if runtime.provider is not None:
        provider_override = pipeline.topology_provider.override(runtime.provider)
    requirements_override = pipeline.topology_requirements.override(
        runtime.to_runtime_requirements()
    )
    with provider_override, requirements_override:
        yield
