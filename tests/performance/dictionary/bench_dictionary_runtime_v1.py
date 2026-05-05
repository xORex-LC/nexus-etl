"""
Бенчмарки Dictionary Layer v1 (`Polars + CSV`) по ADR DEC-001.

Профили:
    - v1_small (200 rows): startup load + lookup hit/miss
    - v1_upper (10k rows): projection/limit lookup при смешанном hit/miss ratio
    - migration_signal (100k rows): warm lookup/contains нагрузка для сигнала v2
    - v1_lazy_cold_start: latency первого обращения в lazy-mode
    - v1_lazy_warm_hit: latency повторного hit после lazy-load
    - v1_exists_hot_path: `contains` hit/miss по key-index

Запуск (быстрый smoke):
    .venv/bin/python tests/performance/dictionary/bench_dictionary_runtime_v1.py --fast -p 1 -n 1 -w 0

Запуск для локального анализа:
    .venv/bin/python tests/performance/dictionary/bench_dictionary_runtime_v1.py --fast -p 1 -n 3 -w 1
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import warnings

import pyperf

warnings.filterwarnings(
    "ignore",
    message=r'Field name "schema" in "DictionarySpec" shadows an attribute in parent "DslBaseModel"',
    category=UserWarning,
)

from connector.domain.dictionary_dsl.specs import DictionaryManifestSpec, DictionarySpec
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader
from connector.infra.dictionaries.provider import PolarsDictionaryProvider
from connector.infra.dictionaries.telemetry import DictionaryTelemetry
from connector.infra.dictionaries.versioning import (
    build_content_sha256_bytes,
    build_dictionary_schema_hash,
)

FAST_MODE = "--fast" in sys.argv
LOOKUP_BATCH_UPPER = 300 if FAST_MODE else 3_000
LOOKUP_BATCH_MIGRATION = 120 if FAST_MODE else 1_000
LOOKUP_BATCH_LAZY_WARM = 400 if FAST_MODE else 4_000
EXISTS_BATCH = 1_000 if FAST_MODE else 20_000
MIX_HIT_RATIO_NUM = 8
MIX_HIT_RATIO_DEN = 10


@dataclass(frozen=True)
class DictionaryBenchFixture:
    """Назначение:
    Подготовленный fixture словаря (CSV на диске + spec/manifest + precomputed workload keys).
    """

    label: str
    row_count: int
    datasets_root: Path
    dict_name: str
    spec: DictionarySpec
    manifest: DictionaryManifestSpec
    hit_key_query: str
    miss_key_query: str
    warm_lookup_queries: tuple[str, ...]
    warm_contains_hit_queries: tuple[str, ...]
    warm_contains_miss_queries: tuple[str, ...]


_TMP_HOLDERS: list[tempfile.TemporaryDirectory[str]] = []


def _make_dictionary_fixture(*, label: str, row_count: int) -> DictionaryBenchFixture:
    tmp = tempfile.TemporaryDirectory(prefix=f"bench-dict-{label}-")
    _TMP_HOLDERS.append(tmp)
    datasets_root = Path(tmp.name) / "datasets"
    dictionaries_dir = datasets_root / "dictionaries"
    dictionaries_dir.mkdir(parents=True, exist_ok=True)

    dict_name = f"org_{label}"
    csv_rel_path = f"dictionaries/{dict_name}.csv"

    header = "code,name,ouid,status,dept\n"
    rows = [header]
    for idx in range(row_count):
        rows.append(
            f"ORG-{idx:06d},Organization {idx},{100000 + idx},"
            f"{'active' if idx % 2 == 0 else 'inactive'},D{idx % 37:02d}\n"
        )
    csv_bytes = "".join(rows).encode("utf-8")
    (dictionaries_dir / f"{dict_name}.csv").write_bytes(csv_bytes)

    spec = DictionarySpec.model_validate(
        {
            "dictionary": dict_name,
            "source": {
                "format": "csv",
                "location": csv_rel_path,
                "csv": {
                    "delimiter": ",",
                    "has_header": True,
                    "encoding": "utf-8",
                    "null_values": ["NULL"],
                },
            },
            "schema": {
                "key_column": {"name": "code"},
                "value_columns": [
                    {"name": "name", "nullable": False},
                    {"name": "ouid", "nullable": False},
                    {"name": "status", "nullable": False},
                    {"name": "dept", "nullable": False},
                ],
                "normalized_key": {"ops": [{"op": "trim"}, {"op": "lower"}]},
            },
            "lookup": {"allow_duplicates": False},
        }
    )
    manifest = DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {
                dict_name: {
                    "csv_path": csv_rel_path,
                    "content_sha256": build_content_sha256_bytes(csv_bytes),
                    "schema_hash": build_dictionary_schema_hash(spec),
                    "row_count": row_count,
                    "updated_at_utc": "2026-02-23T12:00:00Z",
                    "owner": "bench",
                }
            },
        }
    )

    hit_idx = row_count // 2 if row_count else 0
    hit_key = f" org-{hit_idx:06d} "
    miss_key = f" org-missing-{row_count:06d} "
    warm_lookup_queries = tuple(
        f" org-{(idx * 17) % max(1, row_count):06d} " if idx % MIX_HIT_RATIO_DEN < MIX_HIT_RATIO_NUM else miss_key
        for idx in range(LOOKUP_BATCH_UPPER)
    )
    warm_contains_hit_queries = tuple(
        f" org-{(idx * 13) % max(1, row_count):06d} "
        for idx in range(EXISTS_BATCH)
    )
    warm_contains_miss_queries = tuple(
        f" org-miss-{idx:06d} "
        for idx in range(EXISTS_BATCH)
    )

    return DictionaryBenchFixture(
        label=label,
        row_count=row_count,
        datasets_root=datasets_root,
        dict_name=dict_name,
        spec=spec,
        manifest=manifest,
        hit_key_query=hit_key,
        miss_key_query=miss_key,
        warm_lookup_queries=warm_lookup_queries,
        warm_contains_hit_queries=warm_contains_hit_queries,
        warm_contains_miss_queries=warm_contains_miss_queries,
    )


def _build_bundle(fixture: DictionaryBenchFixture):
    return build_dictionary_dsl_runtime(
        specs={fixture.dict_name: fixture.spec},
        manifest_spec=fixture.manifest,
    )


def _make_telemetry() -> DictionaryTelemetry:
    return DictionaryTelemetry(
        fingerprint_salt="bench-dictionary-runtime-v1",
        lookup_hit_sample_percent=0,
        lookup_miss_sample_percent=0,
    )


@dataclass
class _RuntimeObjects:
    backend: PolarsDictionaryBackend
    provider: PolarsDictionaryProvider
    telemetry: DictionaryTelemetry


def _make_runtime(
    fixture: DictionaryBenchFixture,
    *,
    load_strategy: str,
) -> _RuntimeObjects:
    bundle = _build_bundle(fixture)
    telemetry = _make_telemetry()
    loader = CsvDictionaryLoader(
        datasets_root=fixture.datasets_root,
        on_dictionary_loaded=telemetry.record_dictionary_loaded,
    )
    backend = PolarsDictionaryBackend(bundle=bundle)
    telemetry.record_runtime_initialized(
        enabled=True,
        load_strategy=load_strategy,
        declared_dict_names=backend.get_declared_dict_names(),
    )

    if load_strategy == "eager":
        loader.load_into(backend)
    elif load_strategy == "lazy":
        backend.set_lazy_loader(
            lambda dict_name: loader.load_dictionary_into(backend, dict_name=dict_name)
        )
    else:  # pragma: no cover - benchmark script invariant
        raise ValueError(load_strategy)

    provider = PolarsDictionaryProvider(backend=backend, telemetry=telemetry)
    return _RuntimeObjects(backend=backend, provider=provider, telemetry=telemetry)


SMALL_FIXTURE = _make_dictionary_fixture(label="v1_small", row_count=200)
UPPER_FIXTURE = _make_dictionary_fixture(label="v1_upper", row_count=10_000)
MIGRATION_FIXTURE = _make_dictionary_fixture(label="migration_signal", row_count=100_000)

UPPER_RUNTIME = _make_runtime(UPPER_FIXTURE, load_strategy="eager")
MIGRATION_RUNTIME = _make_runtime(MIGRATION_FIXTURE, load_strategy="eager")
LAZY_WARM_RUNTIME = _make_runtime(UPPER_FIXTURE, load_strategy="lazy")
assert LAZY_WARM_RUNTIME.provider.lookup(UPPER_FIXTURE.dict_name, UPPER_FIXTURE.hit_key_query, limit=1)

# Для отдельного профиля `migration_signal` используем свой batch, чтобы не держать слишком длинную итерацию pyperf.
MIGRATION_LOOKUP_QUERIES = tuple(
    f" org-{(idx * 97) % MIGRATION_FIXTURE.row_count:06d} "
    if idx % MIX_HIT_RATIO_DEN < MIX_HIT_RATIO_NUM
    else f" org-migration-miss-{idx:06d} "
    for idx in range(LOOKUP_BATCH_MIGRATION)
)


def bench_v1_small_startup_lookup_hit(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        runtime = _make_runtime(SMALL_FIXTURE, load_strategy="eager")
        rows = runtime.provider.lookup(
            SMALL_FIXTURE.dict_name,
            SMALL_FIXTURE.hit_key_query,
            fields=("name", "ouid"),
            limit=1,
        )
        assert rows
        total += timer() - t0
    return total


def bench_v1_small_startup_lookup_miss(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        runtime = _make_runtime(SMALL_FIXTURE, load_strategy="eager")
        rows = runtime.provider.lookup(
            SMALL_FIXTURE.dict_name,
            SMALL_FIXTURE.miss_key_query,
            fields=("name",),
            limit=1,
        )
        assert rows == []
        total += timer() - t0
    return total


def bench_v1_upper_projection_limit_mix_80_20(loops: int) -> float:
    provider = UPPER_RUNTIME.provider
    dict_name = UPPER_FIXTURE.dict_name
    queries = UPPER_FIXTURE.warm_lookup_queries
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        hits = 0
        for query in queries:
            rows = provider.lookup(dict_name, query, fields=("name", "dept"), limit=1)
            if rows:
                hits += 1
                assert set(rows[0]) == {"name", "dept"}
            else:
                assert rows == []
        assert hits >= (len(queries) * MIX_HIT_RATIO_NUM) // MIX_HIT_RATIO_DEN
        total += timer() - t0
    return total


def bench_v1_lazy_cold_start_lookup_hit(loops: int) -> float:
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        runtime = _make_runtime(UPPER_FIXTURE, load_strategy="lazy")
        rows = runtime.provider.lookup(
            UPPER_FIXTURE.dict_name,
            UPPER_FIXTURE.hit_key_query,
            fields=("name",),
            limit=1,
        )
        assert rows
        total += timer() - t0
    return total


def bench_v1_lazy_warm_hit(loops: int) -> float:
    provider = LAZY_WARM_RUNTIME.provider
    dict_name = UPPER_FIXTURE.dict_name
    query = UPPER_FIXTURE.hit_key_query
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _inner in range(LOOKUP_BATCH_LAZY_WARM):
            rows = provider.lookup(dict_name, query, fields=("name",), limit=1)
            assert rows
        total += timer() - t0
    return total


def bench_v1_exists_hot_path_hit(loops: int) -> float:
    provider = UPPER_RUNTIME.provider
    dict_name = UPPER_FIXTURE.dict_name
    queries = UPPER_FIXTURE.warm_contains_hit_queries
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for query in queries:
            assert provider.contains(dict_name, query) is True
        total += timer() - t0
    return total


def bench_v1_exists_hot_path_miss(loops: int) -> float:
    provider = UPPER_RUNTIME.provider
    dict_name = UPPER_FIXTURE.dict_name
    queries = UPPER_FIXTURE.warm_contains_miss_queries
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for query in queries:
            assert provider.contains(dict_name, query) is False
        total += timer() - t0
    return total


def bench_migration_signal_100k_lookup_contains_mix(loops: int) -> float:
    provider = MIGRATION_RUNTIME.provider
    dict_name = MIGRATION_FIXTURE.dict_name
    queries = MIGRATION_LOOKUP_QUERIES
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for idx, query in enumerate(queries):
            if idx % 3 == 0:
                _ = provider.contains(dict_name, query)
            else:
                rows = provider.lookup(dict_name, query, fields=("name", "ouid"), limit=1)
                if rows:
                    assert set(rows[0]) == {"name", "ouid"}
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func(
        "dictionary_v1_small_startup_lookup_hit_200rows",
        bench_v1_small_startup_lookup_hit,
    )
    runner.bench_time_func(
        "dictionary_v1_small_startup_lookup_miss_200rows",
        bench_v1_small_startup_lookup_miss,
    )
    runner.bench_time_func(
        "dictionary_v1_upper_projection_limit_mix_80_20_10000rows",
        bench_v1_upper_projection_limit_mix_80_20,
    )
    runner.bench_time_func(
        "dictionary_v1_lazy_cold_start_lookup_hit_10000rows",
        bench_v1_lazy_cold_start_lookup_hit,
    )
    runner.bench_time_func(
        "dictionary_v1_lazy_warm_hit_10000rows",
        bench_v1_lazy_warm_hit,
    )
    runner.bench_time_func(
        "dictionary_v1_exists_hot_path_hit_10000rows",
        bench_v1_exists_hot_path_hit,
    )
    runner.bench_time_func(
        "dictionary_v1_exists_hot_path_miss_10000rows",
        bench_v1_exists_hot_path_miss,
    )
    runner.bench_time_func(
        "dictionary_migration_signal_lookup_contains_mix_100000rows",
        bench_migration_signal_100k_lookup_contains_mix,
    )
