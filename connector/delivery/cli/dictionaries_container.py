"""
Назначение:
    DI sub-container для Dictionary runtime v1 (DSL -> backend -> provider -> telemetry).

Граница ответственности:
    - Собирает object graph словарного runtime через dependency-injector.
    - Управляет lifecycle backend Resource (eager init -> no-op teardown).
    - Поддерживает graceful disabled mode, если секция `dictionaries` отсутствует.
    - Не является composition root (им владеет `AppContainer`).
    - Не содержит stage-specific wiring (enrich/import-plan только consumers на уровне app/requirements).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import yaml
from dependency_injector import containers, providers

from connector.config.app_settings import DictionaryRuntimeSettings
from connector.domain.dictionary_dsl import (
    DictionaryRegistrySpec,
    DictionarySpec,
    load_dictionary_manifest_spec,
    load_dictionary_manifest_spec_for_runtime,
    load_dictionary_registry_spec,
    load_dictionary_spec,
    load_enabled_dictionary_specs_for_runtime,
    load_optional_dictionary_registry_spec_for_runtime,
)
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import (
    DictionaryDslRuntimeBundle,
    build_dictionary_dsl_runtime,
)
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader
from connector.infra.dictionaries.provider import PolarsDictionaryProvider
from connector.infra.dictionaries.telemetry import DictionaryTelemetry


def _normalize_datasets_root(datasets_root: str | Path | None) -> Path | None:
    if datasets_root is None:
        return None
    return Path(datasets_root)


def _load_runtime_bundle_optional(
    *,
    datasets_root: str | Path | None,
) -> DictionaryDslRuntimeBundle | None:
    """
    Назначение:
        Собрать optional DSL runtime bundle словарей (без CSV IO).

    Contract:
        - `None` возвращается только для disabled-mode (`dictionaries` section absent)
          или при отсутствии enabled словарей (`items:{}` / all disabled).
        - Ошибки DSL/manifest/compile не подавляются (`DslLoadError` fail-fast).
    """
    root = _normalize_datasets_root(datasets_root)

    if root is None:
        registry = load_optional_dictionary_registry_spec_for_runtime()
        if registry is None:
            return None
        specs = load_enabled_dictionary_specs_for_runtime()
        if not specs:
            return None
        manifest = load_dictionary_manifest_spec_for_runtime()
        return build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)

    registry_path = root / "registry.yml"
    if not _has_dictionaries_section_or_raise(registry_path):
        return None

    registry = load_dictionary_registry_spec(registry_path)
    specs = _load_enabled_specs_from_registry(registry=registry, datasets_root=root)
    if not specs:
        return None
    manifest = load_dictionary_manifest_spec(root / "dictionaries" / "manifest.yml")
    return build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)


def _has_dictionaries_section_or_raise(registry_path: Path) -> bool:
    """
    Назначение:
        Проверить наличие секции `dictionaries` в общем registry-файле для optional mode.

    Контракт:
        - Только отсутствие секции считается disabled-mode.
        - Ошибки чтения/структуры файла остаются fatal (`DICT_DSL_REGISTRY_INVALID`).
    """
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message=f"Failed to read dictionary registry: {exc}",
            details={"path": str(registry_path)},
        ) from exc
    if not isinstance(raw, dict):
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message="Invalid dictionary registry DSL: DSL YAML must be a mapping",
            details={"path": str(registry_path)},
        )
    return "dictionaries" in raw


def _load_enabled_specs_from_registry(
    *,
    registry: DictionaryRegistrySpec,
    datasets_root: Path,
) -> dict[str, DictionarySpec]:
    """
    Назначение:
        Загрузить enabled dictionary spec'и для кастомного `datasets_root` (tests/fixtures).
    """
    specs: dict[str, DictionarySpec] = {}
    seen_declared_names: set[str] = set()

    for dict_name, entry in registry.items.items():
        if not entry.enabled:
            continue
        spec_path = datasets_root / entry.spec
        spec = load_dictionary_spec(spec_path)
        if spec.dictionary != dict_name:
            raise DslLoadError(
                code="DICT_DSL_SPEC_INVALID",
                message=(
                    f"Dictionary spec mismatch: registry key '{dict_name}' "
                    f"!= spec.dictionary '{spec.dictionary}'"
                ),
                details={"dict_name": dict_name, "path": str(spec_path)},
            )
        if spec.dictionary in seen_declared_names:
            raise DslLoadError(
                code="DICT_DSL_SPEC_INVALID",
                message=f"Duplicate dictionary name in specs: '{spec.dictionary}'",
                details={"dict_name": dict_name, "path": str(spec_path)},
            )
        seen_declared_names.add(spec.dictionary)
        specs[dict_name] = spec
    return specs


def _build_csv_loader(*, datasets_root: str | Path | None) -> CsvDictionaryLoader:
    return CsvDictionaryLoader(datasets_root=datasets_root)


def _build_dictionary_telemetry(*, settings: DictionaryRuntimeSettings) -> DictionaryTelemetry:
    """
    Назначение:
        Собрать telemetry-объект словарного runtime из Pydantic settings.
    """
    _ = settings.dictionary_fingerprint_salt_version  # reserved for report/version surface in later stages
    return DictionaryTelemetry(
        fingerprint_salt=settings.dictionary_fingerprint_salt,
        lookup_hit_sample_percent=settings.dictionary_lookup_hit_sample_percent,
        lookup_miss_sample_percent=settings.dictionary_lookup_miss_sample_percent,
    )


def dictionary_backend_resource(
    *,
    dsl_runtime_bundle: DictionaryDslRuntimeBundle | None,
    csv_loader: CsvDictionaryLoader,
    settings: DictionaryRuntimeSettings,
) -> Iterator[PolarsDictionaryBackend | None]:
    """
    Назначение:
        Resource-генератор backend словарей: eager load (fail-fast) -> yield -> no-op teardown.

    Контракт:
        - `dsl_runtime_bundle is None` -> disabled mode (`yield None`).
        - Ошибки DSL/CSV/fingerprint validation пробрасываются как `DslLoadError`.
        - Teardown no-op: runtime read-only in-memory, отдельного close() не требуется.
    """
    _ = settings.dictionary_load_strategy  # Stage 6 will differentiate eager/lazy; Stage 4 keeps fail-fast init.
    if dsl_runtime_bundle is None:
        yield None
        return

    backend = PolarsDictionaryBackend(bundle=dsl_runtime_bundle)
    csv_loader.load_into(backend)
    yield backend


def _build_provider_or_none(
    *,
    backend: PolarsDictionaryBackend | None,
    telemetry: DictionaryTelemetry,
) -> PolarsDictionaryProvider | None:
    if backend is None:
        return None
    return PolarsDictionaryProvider(backend=backend, telemetry=telemetry)


class DictionaryContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI sub-container Dictionary runtime v1.

    Граница ответственности:
        - dsl_runtime_bundle: Singleton (optional DSL compile step, без CSV IO).
        - csv_loader: Singleton (CSV reader/manifest validation orchestration helper).
        - backend: Resource (eager CSV load + in-memory index build).
        - telemetry/provider: Singleton поверх backend Resource.
        - Не является composition root; монтируется в `AppContainer`.
    """

    settings = providers.Dependency(instance_of=DictionaryRuntimeSettings)
    datasets_root = providers.Dependency()

    dsl_runtime_bundle = providers.Singleton(
        _load_runtime_bundle_optional,
        datasets_root=datasets_root,
    )

    csv_loader = providers.Singleton(
        _build_csv_loader,
        datasets_root=datasets_root,
    )

    telemetry = providers.Singleton(
        _build_dictionary_telemetry,
        settings=settings,
    )

    backend = providers.Resource(
        dictionary_backend_resource,
        dsl_runtime_bundle=dsl_runtime_bundle,
        csv_loader=csv_loader,
        settings=settings,
    )

    provider = providers.Singleton(
        _build_provider_or_none,
        backend=backend,
        telemetry=telemetry,
    )


__all__ = ["DictionaryContainer", "dictionary_backend_resource"]
