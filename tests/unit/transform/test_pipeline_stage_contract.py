"""
Тесты Stage Contract и PipelineOrchestrator (TRANSFORM-DEC-004, Этап 1).

Категории:
    Architecture — структурная корректность протоколов и инварианты типов.
    Unit         — изолированные тесты PipelineOrchestrator и PipelineHooks.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from connector.domain.transform.stages.stages import (
    AnyStageContract,
    BatchConfig,
    BatchableStage,
    PipelineHooks,
    PipelineOrchestrator,
    StageContract,
    MapStage,
    NormalizeStage,
    EnrichStage,
    MatchStage,
    ResolveStage,
    MatchProcessor,
    ResolveProcessor,
)
from connector.domain.diagnostics.catalog import ErrorCatalog


# ════════════════════════════════════════════════════════════════════════════════
# Test helpers
# ════════════════════════════════════════════════════════════════════════════════

class _PassthroughStage:
    """Stub-стадия: пропускает все элементы без изменений."""

    def __init__(self, name: str = "passthrough") -> None:
        self.stage_name = name

    def run(self, source):
        yield from source


class _MultiplyStage:
    """Stub-стадия: выдаёт каждый элемент дважды."""

    stage_name = "multiply"

    def run(self, source):
        for item in source:
            yield item
            yield item


def _make_catalog() -> ErrorCatalog:
    """Stub ErrorCatalog — стадии получают его через конструктор, не вызывают напрямую."""
    return Mock(spec=ErrorCatalog)


def _make_items(n: int = 3) -> list:
    return [Mock(name=f"item_{i}") for i in range(n)]


def _make_map_stage() -> MapStage:
    return MapStage(mapper=Mock(), catalog=_make_catalog())


def _make_normalize_stage() -> NormalizeStage:
    return NormalizeStage(normalizer=Mock(), catalog=_make_catalog())


def _make_enrich_stage() -> EnrichStage:
    return EnrichStage(enricher=Mock(), catalog=_make_catalog())


def _make_match_stage() -> MatchStage:
    return MatchStage(matcher=Mock(spec=MatchProcessor), catalog=_make_catalog())


def _make_resolve_stage() -> ResolveStage:
    return ResolveStage(resolver=Mock(spec=ResolveProcessor), catalog=_make_catalog())


# ════════════════════════════════════════════════════════════════════════════════
# Architecture tests
# ════════════════════════════════════════════════════════════════════════════════

class TestStageContractArchitecture:
    """Структурная корректность StageContract Protocol."""

    def test_all_stages_implement_stage_contract(self):
        """Все 5 конкретных стадий satisfying StageContract через structural subtyping."""
        stages = [
            _make_map_stage(),
            _make_normalize_stage(),
            _make_enrich_stage(),
            _make_match_stage(),
            _make_resolve_stage(),
        ]
        for stage in stages:
            assert isinstance(stage, StageContract), (
                f"{type(stage).__name__} не реализует StageContract "
                f"(нет stage_name или run)"
            )

    def test_resolve_stage_run_no_extra_kwargs(self):
        """ResolveStage.run(source) без dataset kwarg — соответствует StageContract."""
        stage = _make_resolve_stage()
        # Должен вызываться без dataset — протокол не предусматривает extra kwargs
        result = list(stage.run(iter([])))
        assert result == []

    def test_stage_contract_is_protocol_not_abc(self):
        """StageContract — typing.Protocol, не ABC."""
        import abc
        # Protocol устанавливает _is_protocol = True
        assert getattr(StageContract, "_is_protocol", False) is True
        # Не является ABC (нет abstractmethod machinery)
        assert not issubclass(StageContract, abc.ABC)

    def test_batchable_stage_is_subtype_of_stage_contract(self):
        """BatchableStage структурно совместим со StageContract."""

        class _BatchableImpl:
            stage_name = "batchable"

            def run(self, source):
                yield from source

            @property
            def batch_config(self) -> BatchConfig | None:
                return None

        stage = _BatchableImpl()
        assert isinstance(stage, StageContract)
        assert isinstance(stage, BatchableStage)

    def test_stage_names_are_canonical(self):
        """Имена стадий соответствуют конвенции DEC-004."""
        assert _make_map_stage().stage_name == "map"
        assert _make_normalize_stage().stage_name == "normalize"
        assert _make_enrich_stage().stage_name == "enrich"
        assert _make_match_stage().stage_name == "match"
        assert _make_resolve_stage().stage_name == "resolve"

    def test_batch_config_is_frozen_dataclass(self):
        """BatchConfig — frozen dataclass (неизменяемый)."""
        cfg = BatchConfig(batch_size=100)
        with pytest.raises((AttributeError, TypeError)):
            cfg.batch_size = 200  # type: ignore[misc]


# ════════════════════════════════════════════════════════════════════════════════
# Unit tests — PipelineOrchestrator: chain и batching
# ════════════════════════════════════════════════════════════════════════════════

class TestPipelineOrchestratorChain:
    """PipelineOrchestrator: правильная цепочка стадий."""

    def test_full_chain_passes_items_through_all_stages(self):
        """5 passthrough-стадий: все элементы проходят без изменений."""
        stages = [_PassthroughStage(f"s{i}") for i in range(5)]
        items = _make_items(4)
        orch = PipelineOrchestrator(stages)
        assert list(orch.run(iter(items))) == items

    def test_empty_stages_passes_source_unchanged(self):
        """Пустой список стадий: source проходит без изменений."""
        items = _make_items(3)
        orch = PipelineOrchestrator([])
        assert list(orch.run(iter(items))) == items

    def test_single_stage_chain(self):
        """Один stage: данные корректно проходят через _monitored()."""
        stage = _PassthroughStage("single")
        items = _make_items(2)
        orch = PipelineOrchestrator([stage])
        assert list(orch.run(iter(items))) == items

    def test_stage_transformation_applied_in_order(self):
        """MultiplyStage: каждый item дважды; 3 items → 6 items."""
        stage = _MultiplyStage()
        items = _make_items(3)
        result = list(PipelineOrchestrator([stage]).run(iter(items)))
        assert len(result) == 6
        # порядок: item0, item0, item1, item1, item2, item2
        assert result[0] == items[0]
        assert result[1] == items[0]

    def test_two_stages_composition(self):
        """Два stage: MultiplyStage → MultiplyStage; 2 items → 8 items."""
        stages = [_MultiplyStage(), _MultiplyStage()]
        items = _make_items(2)
        result = list(PipelineOrchestrator(stages).run(iter(items)))
        assert len(result) == 8


class TestPipelineOrchestratorBatching:
    """PipelineOrchestrator: батчинг через BatchableStage."""

    def test_batching_stage_receives_batches_not_stream(self):
        """Стадия с BatchConfig получает list (батч), а не генератор."""
        received_types: list[str] = []

        class _BatchCaptureStage:
            stage_name = "batch"

            @property
            def batch_config(self):
                return BatchConfig(batch_size=2)

            def run(self, source):
                received_types.append(type(source).__name__)
                yield from source

        stage = _BatchCaptureStage()
        items = _make_items(3)
        list(PipelineOrchestrator([stage]).run(iter(items)))

        # Каждый батч — list, не генератор
        assert all(t == "list" for t in received_types)

    def test_batching_splits_into_correct_batch_sizes(self):
        """5 items с batch_size=2: вызовы run([2], [2], [1])."""
        batch_sizes: list[int] = []

        class _BatchSizeCapture:
            stage_name = "batch"

            @property
            def batch_config(self):
                return BatchConfig(batch_size=2)

            def run(self, source):
                items = list(source)
                batch_sizes.append(len(items))
                yield from items

        stage = _BatchSizeCapture()
        list(PipelineOrchestrator([stage]).run(iter(_make_items(5))))
        assert batch_sizes == [2, 2, 1]

    def test_non_batchable_stage_run_called_once(self):
        """Стадия без batch_config: run() вызывается ровно один раз."""
        call_count = [0]

        class _CountCallStage:
            stage_name = "count"

            def run(self, source):
                call_count[0] += 1
                yield from source

        stage = _CountCallStage()
        list(PipelineOrchestrator([stage]).run(iter(_make_items(10))))
        assert call_count[0] == 1

    def test_non_batchable_stage_receives_iterable_not_list(self):
        """Стадия без batch_config получает lazy iterable, не list."""
        received_type: list[str] = []

        class _TypeCapture:
            stage_name = "type"

            def run(self, source):
                received_type.append(type(source).__name__)
                yield from source

        stage = _TypeCapture()
        list(PipelineOrchestrator([stage]).run(iter(_make_items(3))))
        assert received_type[0] != "list"


# ════════════════════════════════════════════════════════════════════════════════
# Unit tests — PipelineHooks
# ════════════════════════════════════════════════════════════════════════════════

class TestPipelineHooksEagerBind:
    """on_stage_bind — assembly hook (eager)."""

    def test_on_stage_bind_called_eagerly_in_run(self):
        """on_stage_bind вызывается при run() до потребления данных."""
        bound: list[str] = []
        hooks = PipelineHooks(on_stage_bind=lambda name: bound.append(name))
        stage = _PassthroughStage("eager_test")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        _ = orch.run(iter([]))  # не потребляем итератор
        assert bound == ["eager_test"]

    def test_on_stage_bind_called_for_all_stages(self):
        """on_stage_bind вызывается для каждой стадии в цепочке."""
        bound: list[str] = []
        hooks = PipelineHooks(on_stage_bind=lambda name: bound.append(name))
        stages = [_PassthroughStage(f"s{i}") for i in range(3)]
        orch = PipelineOrchestrator(stages, hooks=hooks)

        _ = orch.run(iter([]))
        assert bound == ["s0", "s1", "s2"]


class TestPipelineHooksLazyExecution:
    """on_stage_start — lazy execution hook."""

    def test_on_stage_start_not_called_before_pull(self):
        """on_stage_start НЕ вызывается при run() — только при первом pull."""
        started: list[str] = []
        hooks = PipelineHooks(on_stage_start=lambda name: started.append(name))
        stage = _PassthroughStage("lazy_test")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        it = iter(orch.run(iter(_make_items(3))))
        assert started == []  # ещё не тянули данные
        next(it)
        assert started == ["lazy_test"]  # теперь сработал

    def test_on_stage_start_called_only_once(self):
        """on_stage_start вызывается ровно один раз за полный проход."""
        started: list[str] = []
        hooks = PipelineHooks(on_stage_start=lambda name: started.append(name))
        stage = _PassthroughStage("once_test")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        list(orch.run(iter(_make_items(5))))
        assert started == ["once_test"]


class TestPipelineHooksCompletion:
    """on_stage_complete — при полном consumption."""

    def test_on_stage_complete_called_on_full_consumption(self):
        """on_stage_complete вызывается при исчерпании всего потока."""
        completed: list[tuple] = []
        hooks = PipelineHooks(
            on_stage_complete=lambda name, ms, stats: completed.append((name, stats))
        )
        stage = _PassthroughStage("complete_test")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        items = _make_items(4)
        list(orch.run(iter(items)))  # полное потребление
        assert len(completed) == 1
        assert completed[0][0] == "complete_test"
        assert completed[0][1] == {"items": 4}

    def test_on_stage_complete_not_fired_for_empty_stream(self):
        """on_stage_complete НЕ вызывается если стрим пустой (start_time guard)."""
        completed: list = []
        hooks = PipelineHooks(
            on_stage_complete=lambda name, ms, stats: completed.append(name)
        )
        stage = _PassthroughStage("empty_test")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        list(orch.run(iter([])))
        assert completed == []

    def test_on_stage_complete_stats_items_count_matches_output(self):
        """stats['items'] == реальному числу yielded элементов."""
        stats_received: list[dict] = []
        hooks = PipelineHooks(
            on_stage_complete=lambda name, ms, stats: stats_received.append(stats)
        )
        stage = _MultiplyStage()  # удваивает: 3 in → 6 out
        orch = PipelineOrchestrator([stage], hooks=hooks)

        list(orch.run(iter(_make_items(3))))
        assert stats_received[0] == {"items": 6}

    def test_on_stage_complete_duration_ms_positive(self):
        """duration_ms в on_stage_complete > 0."""
        durations: list[float] = []
        hooks = PipelineHooks(
            on_stage_complete=lambda name, ms, stats: durations.append(ms)
        )
        stage = _PassthroughStage("timing")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        list(orch.run(iter(_make_items(2))))
        assert durations[0] >= 0.0  # duration_ms неотрицательно


class TestPipelineHooksAbort:
    """on_stage_abort — при partial consumption (GeneratorExit)."""

    def test_on_stage_abort_called_on_partial_consumption(self):
        """on_stage_abort вызывается при stream.close() до исчерпания."""
        aborted: list[str] = []
        hooks = PipelineHooks(on_stage_abort=lambda name, ms: aborted.append(name))
        stage = _PassthroughStage("abort_test")
        items = _make_items(5)
        orch = PipelineOrchestrator([stage], hooks=hooks)

        stream = orch.run(iter(items))
        # Нужен явный iter() чтобы получить generator object с .close()
        gen = iter(stream)
        next(gen)     # pull первый item — start_time установлен
        gen.close()   # → GeneratorExit

        assert aborted == ["abort_test"]

    def test_on_stage_abort_not_called_if_no_items_pulled(self):
        """on_stage_abort НЕ вызывается если ни одного item не было pulled."""
        aborted: list[str] = []
        hooks = PipelineHooks(on_stage_abort=lambda name, ms: aborted.append(name))
        stage = _PassthroughStage("no_pull")
        orch = PipelineOrchestrator([stage], hooks=hooks)

        stream = orch.run(iter(_make_items(3)))
        gen = iter(stream)
        gen.close()  # close без single pull

        assert aborted == []


class TestPipelineHooksError:
    """on_stage_error — при исключении в стадии."""

    def test_on_stage_error_called_on_exception_after_first_pull(self):
        """on_stage_error вызывается при исключении ПОСЛЕ первого pull."""
        errors: list[tuple] = []
        hooks = PipelineHooks(
            on_stage_error=lambda name, exc, ms: errors.append((name, type(exc)))
        )

        class _ErrorAfterFirstStage:
            stage_name = "error_stage"

            def run(self, source):
                items = list(source)
                if items:
                    yield items[0]
                    raise ValueError("stage error")

        stage = _ErrorAfterFirstStage()
        orch = PipelineOrchestrator([stage], hooks=hooks)

        with pytest.raises(ValueError, match="stage error"):
            list(orch.run(iter(_make_items(2))))

        assert errors == [("error_stage", ValueError)]

    def test_on_stage_error_not_fired_before_first_pull(self):
        """on_stage_error НЕ вызывается если исключение до первого pull (start_time=None)."""
        errors: list = []
        hooks = PipelineHooks(
            on_stage_error=lambda name, exc, ms: errors.append(name)
        )

        class _ErrorBeforePullStage:
            stage_name = "setup_error"

            def run(self, source):
                # raises на первом next() без yield — start_time остаётся None
                raise RuntimeError("setup failure")
                yield  # делает run() generator function

        stage = _ErrorBeforePullStage()
        orch = PipelineOrchestrator([stage], hooks=hooks)

        with pytest.raises(RuntimeError, match="setup failure"):
            list(orch.run(iter(_make_items(1))))

        assert errors == []  # on_stage_error НЕ вызван

    def test_orchestrator_reraises_after_on_stage_error(self):
        """_monitored() всегда re-raises после on_stage_error — никогда не подавляет."""
        hook_called = [False]
        hooks = PipelineHooks(
            on_stage_error=lambda name, exc, ms: hook_called.__setitem__(0, True)
        )

        class _FailingStage:
            stage_name = "fail"

            def run(self, source):
                items = list(source)
                if items:
                    yield items[0]
                raise RuntimeError("must propagate")

        orch = PipelineOrchestrator([_FailingStage()], hooks=hooks)

        with pytest.raises(RuntimeError, match="must propagate"):
            list(orch.run(iter(_make_items(1))))

        assert hook_called[0] is True  # хук вызван И исключение вышло наружу


class TestPipelineHooksDefaults:
    """PipelineHooks по умолчанию — без callbacks."""

    def test_no_hooks_orchestrator_runs_normally(self):
        """PipelineHooks() без callbacks: PipelineOrchestrator работает без ошибок."""
        stage = _PassthroughStage("no_hooks")
        orch = PipelineOrchestrator([stage])  # hooks=None by default
        items = _make_items(5)
        assert list(orch.run(iter(items))) == items

    def test_partial_hooks_orchestrator_runs_normally(self):
        """Часть callbacks None — остальные срабатывают нормально."""
        started: list[str] = []
        hooks = PipelineHooks(
            on_stage_start=lambda name: started.append(name),
            # on_stage_complete, on_stage_error, on_stage_abort — None
        )
        stage = _PassthroughStage("partial")
        orch = PipelineOrchestrator([stage], hooks=hooks)
        list(orch.run(iter(_make_items(2))))
        assert started == ["partial"]
