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

from connector.common.runtime_paths import (
    get_runtime_paths,
    resolve_registry_path_for_datasets_root,
)
from connector.config.models import DictionaryConfig
from connector.domain.dictionary_dsl import (
    DictionaryRegistrySpec,
    DictionarySpec,
    load_dictionary_manifest_spec,
    load_dictionary_manifest_spec_for_registry,
    load_dictionary_registry_spec,
    load_dictionary_spec,
    load_enabled_dictionary_specs_for_runtime,
    load_optional_dictionary_registry_spec_for_runtime,
)
from connector.domain.dsl.loader import registry_path as active_dsl_registry_path
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import (
    DictionaryDslRuntimeBundle,
    build_dictionary_dsl_runtime,
)
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader
from connector.infra.dictionaries.provider import PolarsDictionaryProvider
from connector.infra.dictionaries.telemetry import DictionaryTelemetry


def _normalize_optional_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    path_obj = Path(path).expanduser()
    if path_obj.is_absolute():
        return path_obj.resolve()
    return (get_runtime_paths().root / path_obj).resolve()


def _load_runtime_bundle_optional(
    *,
    registry_path: str | Path | None,
    dictionary_specs_root: str | Path | None,
) -> DictionaryDslRuntimeBundle | None:
    """
    Назначение:
        Собрать optional DSL runtime bundle словарей (без CSV IO).

    Contract:
        - `None` возвращается только для disabled-mode (`dictionaries` section absent).
        - Пустой registry (`items:{}` / all disabled) -> валидный empty runtime bundle.
        - Ошибки DSL/manifest/compile не подавляются (`DslLoadError` fail-fast).
    """
    registry_override = _normalize_optional_path(registry_path)
    dictionary_specs_root_override = _normalize_optional_path(dictionary_specs_root)

    if registry_override is None and dictionary_specs_root_override is None:
        registry = load_optional_dictionary_registry_spec_for_runtime()
        if registry is None:
            return None
        specs = load_enabled_dictionary_specs_for_runtime()
        manifest = load_dictionary_manifest_spec_for_registry(registry)
        return build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)

    active_registry_path = registry_override
    if active_registry_path is None:
        active_registry_path = active_dsl_registry_path()

    if not _has_dictionaries_section_or_raise(active_registry_path):
        return None

    specs_root = dictionary_specs_root_override
    if specs_root is None:
        specs_root = get_runtime_paths().dictionary_specs_root

    registry = load_dictionary_registry_spec(active_registry_path)
    specs = _load_enabled_specs_from_registry(registry=registry, dictionary_specs_root=specs_root)
    manifest = load_dictionary_manifest_spec(specs_root / registry.manifest)
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
    dictionary_specs_root: Path,
) -> dict[str, DictionarySpec]:
    """
    Назначение:
        Загрузить enabled dictionary spec'и для кастомного `dictionary_specs_root`.
    """
    specs: dict[str, DictionarySpec] = {}
    seen_declared_names: set[str] = set()

    for dict_name, entry in registry.items.items():
        if not entry.enabled:
            continue
        spec_path = dictionary_specs_root / entry.spec
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


def _build_csv_loader(
    *,
    dictionary_data_root: str | Path | None,
    telemetry: DictionaryTelemetry,
) -> CsvDictionaryLoader:
    return CsvDictionaryLoader(
        dictionary_data_root=dictionary_data_root,
        on_dictionary_loaded=telemetry.record_dictionary_loaded,
    )


def _build_dictionary_telemetry(*, settings: DictionaryConfig) -> DictionaryTelemetry:
    """
    Назначение:
        Собрать telemetry-объект словарного runtime из Pydantic settings.
    """
    _ = settings.fingerprint_salt_version  # reserved for report/version surface in later stages
    return DictionaryTelemetry(
        fingerprint_salt=settings.fingerprint_salt,
        lookup_hit_sample_percent=settings.lookup_hit_sample_percent,
        lookup_miss_sample_percent=settings.lookup_miss_sample_percent,
    )


def dictionary_backend_resource(
    *,
    dsl_runtime_bundle: DictionaryDslRuntimeBundle | None,
    csv_loader: CsvDictionaryLoader,
    settings: DictionaryConfig,
    telemetry: DictionaryTelemetry,
) -> Iterator[PolarsDictionaryBackend | None]:
    """
    Назначение:
        Resource-генератор backend словарей: init runtime state -> eager/lazy policy -> yield -> no-op teardown.

    Контракт:
        - `dsl_runtime_bundle is None` -> disabled mode (`yield None`).
        - `eager`: все CSV загружаются на startup (fail-fast на CSV/fingerprint/schema).
        - `lazy`: CSV грузится по первому обращению к конкретному словарю.
        - Ошибки DSL/CSV/fingerprint/schema validation пробрасываются как `DslLoadError`.
        - Teardown no-op: runtime read-only in-memory, отдельного close() не требуется.
    """
    load_strategy = settings.load_strategy
    if dsl_runtime_bundle is None:
        telemetry.record_runtime_initialized(
            enabled=False,
            load_strategy=load_strategy,
            declared_dict_names=(),
        )
        yield None
        return

    backend = PolarsDictionaryBackend(bundle=dsl_runtime_bundle)
    telemetry.record_runtime_initialized(
        enabled=True,
        load_strategy=load_strategy,
        declared_dict_names=backend.get_declared_dict_names(),
    )

    if load_strategy == "eager":
        csv_loader.load_into(backend)
    elif load_strategy == "lazy":
        backend.set_lazy_loader(
            lambda dict_name: csv_loader.load_dictionary_into(backend, dict_name=dict_name)
        )
    else:
        raise DslLoadError(
            code="DICT_RUNTIME_INIT_FAILED",
            message=f"Unsupported dictionary_load_strategy: '{load_strategy}'",
            details={"load_strategy": load_strategy},
        )
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
        - backend: Resource (eager/lazy policy + in-memory index lifecycle).
        - telemetry/provider: Singleton поверх backend Resource.
        - Не является composition root; монтируется в `AppContainer`.
    """

    settings = providers.Dependency(instance_of=DictionaryConfig)
    registry_path = providers.Dependency()
    dictionary_specs_root = providers.Dependency()
    dictionary_data_root = providers.Dependency()

    dsl_runtime_bundle = providers.Singleton(
        _load_runtime_bundle_optional,
        registry_path=registry_path,
        dictionary_specs_root=dictionary_specs_root,
    )

    telemetry = providers.Singleton(
        _build_dictionary_telemetry,
        settings=settings,
    )

    csv_loader = providers.Singleton(
        _build_csv_loader,
        dictionary_data_root=dictionary_data_root,
        telemetry=telemetry,
    )

    backend = providers.Resource(
        dictionary_backend_resource,
        dsl_runtime_bundle=dsl_runtime_bundle,
        csv_loader=csv_loader,
        settings=settings,
        telemetry=telemetry,
    )

    provider = providers.Singleton(
        _build_provider_or_none,
        backend=backend,
        telemetry=telemetry,
    )


__all__ = ["DictionaryContainer", "dictionary_backend_resource"]
