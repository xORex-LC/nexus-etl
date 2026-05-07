"""Назначение:
    Реестр DatasetSpec factories с auto-discovery из `datasets/registry.yml`.

Граница ответственности:
    - Owns: выбор factory по имени датасета, auto-discovery и eager registry validation.
    - Owns: strict validation policy для custom `spec_class` factories.
    - Does NOT: детали eager YAML loading и runtime accessor behavior самих DatasetSpec.
"""

from __future__ import annotations

import importlib
import inspect
from functools import partial
from typing import Any, Callable

from connector.datasets.spec import DatasetSpec
from connector.domain.dsl.loader import load_registry
from connector.domain.ports.secrets.provider import SecretProviderProtocol

_REQUIRED_DATASET_SPEC_MEMBERS = (
    "build_spec_for",
    "build_record_source",
    "get_report_adapter",
    "get_apply_adapter",
    "get_diagnostic_catalog",
)


def _make_yaml_spec(
    dataset_name: str,
    secrets: SecretProviderProtocol | None = None,
) -> DatasetSpec:
    from connector.datasets.yaml_spec import YamlDatasetSpec
    from connector.datasets.yaml_spec_loader import load_yaml_dataset_artifacts

    artifacts = load_yaml_dataset_artifacts(dataset_name)
    return YamlDatasetSpec(artifacts, secrets)


def _format_spec_class_error(dataset_name: str, spec_class_ref: str, reason: str) -> str:
    return (
        f"Invalid spec_class for dataset '{dataset_name}' ({spec_class_ref!r}): {reason}"
    )


def _import_spec_symbol(dataset_name: str, spec_class_ref: str) -> Any:
    """Назначение:
        Импортировать symbol для custom dataset factory по строковой ссылке.

    Контракт:
        Формат ref — `module.path:factory_function` или `module.path:ClassName`.
    """
    module_path, _, attr_name = spec_class_ref.rpartition(":")
    if not module_path or not attr_name:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "expected format 'module.path:factory_or_class'",
            )
        )
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _assert_custom_factory_signature(
    dataset_name: str,
    spec_class_ref: str,
    symbol: Any,
) -> None:
    """Назначение:
        Проверить строгий factory contract для `spec_class`.

    Контракт:
        - symbol callable;
        - принимает keyword `secrets`;
        - `secrets` optional (имеет default);
        - positional-only / required `secrets` не поддерживаются.
    """
    if not callable(symbol):
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "imported symbol must be callable",
            )
        )

    try:
        signature = inspect.signature(symbol)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "callable signature is not introspectable",
            )
        ) from exc

    parameter = signature.parameters.get("secrets")
    if parameter is None:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "factory must declare optional keyword parameter 'secrets'",
            )
        )

    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "parameter 'secrets' must be keyword-compatible",
            )
        )

    if parameter.default is inspect.Parameter.empty:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "parameter 'secrets' must be optional and default to None or another value",
            )
        )


def _assert_dataset_spec_instance(
    dataset_name: str,
    spec_class_ref: str,
    instance: Any,
) -> None:
    """Назначение:
        Валидировать DatasetSpec instance на уровне registry policy.

    Контракт:
        - объект обязан иметь dataset_name и обязательные DatasetSpec methods;
        - instance.dataset_name должен совпадать с ключом датасета в registry.yml.
    """
    instance_dataset_name = getattr(instance, "dataset_name", None)
    if not isinstance(instance_dataset_name, str) or not instance_dataset_name:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "factory must return DatasetSpec with non-empty 'dataset_name'",
            )
        )

    missing_members = [
        member_name
        for member_name in _REQUIRED_DATASET_SPEC_MEMBERS
        if not callable(getattr(instance, member_name, None))
    ]
    if missing_members:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                "factory must return DatasetSpec with methods: "
                + ", ".join(_REQUIRED_DATASET_SPEC_MEMBERS)
                + f"; missing: {', '.join(missing_members)}",
            )
        )

    if instance_dataset_name != dataset_name:
        raise ValueError(
            _format_spec_class_error(
                dataset_name,
                spec_class_ref,
                f"factory returned dataset_name={instance_dataset_name!r}, expected {dataset_name!r}",
            )
        )


def _resolve_spec_factory(
    dataset_name: str,
    spec_class_ref: str,
) -> Callable[..., DatasetSpec]:
    """Назначение:
        Нормализовать `spec_class` в factory с единым контрактом `factory(*, secrets=None)`.
    """
    symbol = _import_spec_symbol(dataset_name, spec_class_ref)
    _assert_custom_factory_signature(dataset_name, spec_class_ref, symbol)

    def _factory(*, secrets: SecretProviderProtocol | None = None) -> DatasetSpec:
        try:
            instance = symbol(secrets=secrets)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                _format_spec_class_error(
                    dataset_name,
                    spec_class_ref,
                    "factory call failed for keyword 'secrets': "
                    f"{type(exc).__name__}: {exc}",
                )
            ) from exc

        _assert_dataset_spec_instance(dataset_name, spec_class_ref, instance)
        return instance

    return _factory


def _build_registry() -> dict[str, Callable[..., DatasetSpec]]:
    """
    Назначение:
        Auto-discovery датасетов из registry.yml.
    """
    registry_data = load_registry()
    datasets = registry_data.get("datasets") or {}
    result: dict[str, Callable[..., DatasetSpec]] = {}
    for name, entry in datasets.items():
        spec_class_ref = entry.get("spec_class") if isinstance(entry, dict) else None
        if spec_class_ref:
            result[name] = _resolve_spec_factory(name, spec_class_ref)
        else:
            result[name] = partial(_make_yaml_spec, name)
    return result


_registry: dict[str, Callable[..., DatasetSpec]] | None = None


def _get_registry() -> dict[str, Callable[..., DatasetSpec]]:
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_spec(dataset: str, secrets: SecretProviderProtocol | None = None) -> DatasetSpec:
    """
    Возвращает DatasetSpec по имени или ValueError, если не зарегистрирован.
    """
    registry = _get_registry()
    try:
        factory = registry[dataset]
        return factory(secrets=secrets)
    except KeyError as exc:
        raise ValueError(f"Unsupported dataset: {dataset}") from exc


def list_specs(secrets: SecretProviderProtocol | None = None) -> list[DatasetSpec]:
    registry = _get_registry()
    return [factory(secrets=secrets) for factory in registry.values()]


def validate_registry() -> None:
    """
    Назначение:
        Eagerly validate all dataset registrations before runtime command path.

    Контракт:
        - для YAML-driven datasets загружает полный snapshot артефактов;
        - для `spec_class` eagerly вызывает strict factory с `secrets=None`;
        - не кеширует preloaded spec объекты глобально.
    """
    from connector.datasets.yaml_spec_loader import load_yaml_dataset_artifacts

    registry_data = load_registry()
    datasets = registry_data.get("datasets") or {}
    for name, entry in datasets.items():
        spec_class_ref = entry.get("spec_class") if isinstance(entry, dict) else None
        if spec_class_ref:
            _resolve_spec_factory(name, spec_class_ref)(secrets=None)
            continue
        load_yaml_dataset_artifacts(name)


def resolve_dataset_name(dataset: str | None, default: str) -> str:
    """
    Назначение:
        Определить имя датасета с учётом значения по умолчанию.
    """
    return dataset if dataset is not None else default


def build_identity_index_plan(
    secrets: SecretProviderProtocol | None = None,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    Возвращает:
        keys_by_dataset: какие ключи индексировать для identity_index (dataset -> set[key_name]).
        id_field_by_dataset: поле resolved_id для датасета (dataset -> field_name).
    """
    keys_by_dataset: dict[str, set[str]] = {}
    id_field_by_dataset: dict[str, str] = {}
    for spec in list_specs(secrets=secrets):
        resolve_spec = spec.build_spec_for("resolve")
        for link_spec in resolve_spec.resolve.links:
            dataset = link_spec.target_dataset
            if dataset in id_field_by_dataset and id_field_by_dataset[dataset] != link_spec.target_id_field:
                raise ValueError(
                    "conflicting target_id_field for dataset "
                    f"{dataset}: {id_field_by_dataset[dataset]} vs {link_spec.target_id_field}"
                )
            id_field_by_dataset.setdefault(dataset, link_spec.target_id_field)
            keys = keys_by_dataset.setdefault(dataset, set())
            keys.update(key_rule.name for key_rule in link_spec.resolve_keys)
            for dedup in link_spec.dedup_rules:
                keys.update(dedup)
    return keys_by_dataset, id_field_by_dataset
