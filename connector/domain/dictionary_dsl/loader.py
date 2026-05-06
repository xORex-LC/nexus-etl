"""
Назначение:
    Загрузка Dictionary DSL-конфигураций: registry, dictionary spec и manifest.

Граница ответственности:
    - Читает YAML и валидирует его через Pydantic-модели dictionary_dsl.
    - Оборачивает ошибки чтения/валидации в `DslLoadError` с `DICT_*` кодами.
    - НЕ выполняет runtime lookup/CSV load и НЕ выбирает backend реализации.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader._common import (
    _read_yaml,
    _registry_path as _active_registry_path,
    _resolve_dictionary_manifest_path,
    _resolve_dictionary_spec_path,
)
from connector.domain.dictionary_dsl.specs import (
    DictionaryManifestSpec,
    DictionaryRegistrySpec,
    DictionarySpec,
)


def load_dictionary_registry_spec(path: str | Path | None = None) -> DictionaryRegistrySpec:
    """
    Назначение:
        Загрузить dictionary registry из отдельного файла или `datasets/registry.yml`.

    Контракт:
        - Если передан общий `datasets/registry.yml`, извлекается секция `dictionaries`.
        - Если передан standalone файл, допускается payload без верхнего ключа `dictionaries`.
    """
    registry_path = Path(path) if path is not None else _registry_path()
    try:
        raw = _read_yaml(registry_path)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message=f"Failed to read dictionary registry: {exc}",
            details={"path": str(registry_path)},
        ) from exc

    payload = _extract_dictionary_registry_payload(raw, allow_missing=False)
    return _validate_registry_or_raise(path=registry_path, payload=payload)


def load_optional_dictionary_registry_spec_for_runtime() -> DictionaryRegistrySpec | None:
    """
    Назначение:
        Runtime helper для optional dictionary runtime.

    Контракт:
        - Если секция `dictionaries` отсутствует в `datasets/registry.yml`, возвращает `None`.
        - Ошибки чтения файла registry и невалидная секция `dictionaries` остаются fatal.
    """
    registry_path = _registry_path()
    try:
        raw = _read_yaml(registry_path)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message=f"Failed to read dictionary registry: {exc}",
            details={"path": str(registry_path)},
        ) from exc

    payload = _extract_dictionary_registry_payload(raw, allow_missing=True)
    if payload is None:
        return None
    return _validate_registry_or_raise(path=registry_path, payload=payload)


def load_dictionary_registry_spec_for_runtime() -> DictionaryRegistrySpec:
    """
    Назначение:
        Strict runtime helper для загрузки dictionary registry из `datasets/registry.yml`.
    """
    return load_dictionary_registry_spec(None)


def load_dictionary_spec(path: str | Path) -> DictionarySpec:
    """
    Назначение:
        Загрузить один `*.dictionary.yaml` и провалидировать как `DictionarySpec`.
    """
    path_obj = Path(path)
    try:
        raw = _read_yaml(path_obj)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_SPEC_INVALID",
            message=f"Failed to read dictionary spec: {exc}",
            details={"path": str(path_obj)},
        ) from exc
    try:
        return DictionarySpec.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_SPEC_INVALID",
            message=f"Invalid dictionary spec DSL: {exc}",
            details={"path": str(path_obj)},
        ) from exc


def load_dictionary_spec_for_runtime(dict_name: str) -> DictionarySpec:
    """
    Назначение:
        Загрузить dictionary spec по имени словаря из registry.
    """
    registry = load_dictionary_registry_spec_for_runtime()
    entry = registry.items.get(dict_name)
    if entry is None:
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message=f"Dictionary '{dict_name}' is not present in dictionary registry",
            details={"dict_name": dict_name, "path": str(_registry_path())},
        )
    spec_path = _resolve_dictionary_spec_path(entry.spec)
    spec = load_dictionary_spec(spec_path)
    _validate_registry_key_matches_spec(dict_name=dict_name, spec=spec, path=spec_path)
    return spec


def load_enabled_dictionary_specs_for_runtime() -> dict[str, DictionarySpec]:
    """
    Назначение:
        Загрузить все enabled dictionary spec'и из registry в единый словарь.

    Контракт:
        - Ключ результирующего dict совпадает с ключом в registry.
        - `spec.dictionary` обязан совпадать с ключом registry (fail-fast).
    """
    registry = load_dictionary_registry_spec_for_runtime()
    specs: dict[str, DictionarySpec] = {}
    seen_declared_names: set[str] = set()

    for dict_name, entry in registry.items.items():
        if not entry.enabled:
            continue
        spec_path = _resolve_dictionary_spec_path(entry.spec)
        spec = load_dictionary_spec(spec_path)
        _validate_registry_key_matches_spec(dict_name=dict_name, spec=spec, path=spec_path)
        if spec.dictionary in seen_declared_names:
            raise DslLoadError(
                code="DICT_DSL_SPEC_INVALID",
                message=f"Duplicate dictionary name in specs: '{spec.dictionary}'",
                details={"dict_name": dict_name, "path": str(spec_path)},
            )
        seen_declared_names.add(spec.dictionary)
        specs[dict_name] = spec
    return specs


def load_dictionary_manifest_spec_for_registry(
    registry: DictionaryRegistrySpec,
    *,
    datasets_root: str | Path | None = None,
) -> DictionaryManifestSpec:
    """
    Назначение:
        Загрузить manifest по пути, объявленному в dictionary registry.
    """
    if datasets_root is not None:
        root = Path(datasets_root)
        return load_dictionary_manifest_spec(root / registry.manifest)
    return load_dictionary_manifest_spec(_resolve_dictionary_manifest_path(registry.manifest))


def load_dictionary_manifest_spec(path: str | Path) -> DictionaryManifestSpec:
    """
    Назначение:
        Загрузить manifest по явному пути.

    Контракт:
        - Отсутствующий файл -> `DICT_SOURCE_MANIFEST_MISSING`.
        - Ошибка чтения/структуры/валидации -> `DICT_SOURCE_MANIFEST_INVALID`.
    """
    manifest_path = Path(path)
    try:
        raw = _read_yaml(manifest_path)
    except FileNotFoundError as exc:
        raise DslLoadError(
            code="DICT_SOURCE_MANIFEST_MISSING",
            message=f"Dictionary manifest file is missing: {manifest_path}",
            details={"path": str(manifest_path)},
        ) from exc
    except Exception as exc:
        raise DslLoadError(
            code="DICT_SOURCE_MANIFEST_INVALID",
            message=f"Failed to read dictionary manifest: {exc}",
            details={"path": str(manifest_path)},
        ) from exc

    try:
        return DictionaryManifestSpec.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_SOURCE_MANIFEST_INVALID",
            message=f"Invalid dictionary manifest DSL: {exc}",
            details={"path": str(manifest_path)},
        ) from exc


def load_dictionary_manifest_spec_for_runtime() -> DictionaryManifestSpec:
    """
    Назначение:
        Runtime helper для manifest path, объявленного в active dictionary registry.
    """
    registry = load_dictionary_registry_spec_for_runtime()
    return load_dictionary_manifest_spec_for_registry(registry)


def _registry_path() -> Path:
    return _active_registry_path()

def _extract_dictionary_registry_payload(
    raw: dict[str, Any],
    *,
    allow_missing: bool,
) -> dict[str, Any] | None:
    """
    Назначение:
        Выделить payload dictionary registry из общего `datasets/registry.yml`.
    """
    if "dictionaries" in raw:
        payload = raw.get("dictionaries")
        if isinstance(payload, dict):
            return payload
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message="dictionaries section must be a mapping",
        )

    if {"version", "items"} <= set(raw.keys()):
        return raw

    if allow_missing:
        return None

    raise DslLoadError(
        code="DICT_DSL_REGISTRY_INVALID",
        message="dictionaries section is missing in registry file",
    )


def _validate_registry_or_raise(*, path: Path, payload: dict[str, Any]) -> DictionaryRegistrySpec:
    try:
        return DictionaryRegistrySpec.model_validate(payload)
    except Exception as exc:
        raise DslLoadError(
            code="DICT_DSL_REGISTRY_INVALID",
            message=f"Invalid dictionary registry DSL: {exc}",
            details={"path": str(path)},
        ) from exc


def _validate_registry_key_matches_spec(
    *,
    dict_name: str,
    spec: DictionarySpec,
    path: Path,
) -> None:
    """Назначение:
        Fail-fast проверить соответствие ключа registry и `spec.dictionary`.
    """
    if spec.dictionary != dict_name:
        raise DslLoadError(
            code="DICT_DSL_SPEC_INVALID",
            message=(
                f"Dictionary spec mismatch: registry key '{dict_name}' "
                f"!= spec.dictionary '{spec.dictionary}'"
            ),
            details={"dict_name": dict_name, "path": str(path)},
        )


__all__ = [
    "load_dictionary_manifest_spec",
    "load_dictionary_manifest_spec_for_registry",
    "load_dictionary_manifest_spec_for_runtime",
    "load_dictionary_registry_spec",
    "load_dictionary_registry_spec_for_runtime",
    "load_dictionary_spec",
    "load_dictionary_spec_for_runtime",
    "load_enabled_dictionary_specs_for_runtime",
    "load_optional_dictionary_registry_spec_for_runtime",
]
