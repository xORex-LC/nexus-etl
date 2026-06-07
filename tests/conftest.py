from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from connector.common.runtime_paths import RuntimePathOverrides
from connector.datasets import registry as dataset_registry_module
from connector.domain.dsl.loader import configure_registry_path, configure_runtime_paths
from tests.runtime_test_support import (
    TEST_RUNTIME_ROOT_ENV,
    build_isolated_test_runtime_root,
    tracked_employees_runtime_roots,
)


# NOTE:
# На CI/локальных тестах режим WAL в некоторых средах может инициализироваться
# очень медленно для каждого нового файла БД. Для тестового контура достаточно
# режима DELETE, он существенно быстрее на cold-start.
os.environ.setdefault("ANKEY_SQLITE__CACHE_JOURNAL_MODE", "DELETE")
os.environ.setdefault(
    TEST_RUNTIME_ROOT_ENV,
    str(Path(tempfile.mkdtemp(prefix="ankey-test-runtime-")).resolve()),
)
build_isolated_test_runtime_root(Path(os.environ[TEST_RUNTIME_ROOT_ENV]))


def _activate_employees_test_registry() -> Path:
    """
    Назначение:
        Включить изолированный `datasets/registry.yaml` как default registry для тестового рантайма.

    Почему это здесь:
        Часть тестов строит `build_catalog()/get_spec()/load_*_for_dataset()` на уровне
        импорта модуля, то есть раньше обычных function-fixtures. Поэтому test runtime
        нужно подготовить и активировать уже при загрузке `conftest.py`.
    """
    roots = tracked_employees_runtime_roots()
    registry_path = roots["registry_path"]
    configure_runtime_paths(
        RuntimePathOverrides(
            datasets_root=roots["datasets_root"],
            dictionary_specs_root=roots["dictionary_specs_root"],
            dictionary_data_root=roots["dictionary_data_root"],
            source_projection_root=roots["source_projection_root"],
            target_projection_root=roots["target_projection_root"],
            source_data_root=roots["source_data_root"],
        )
    )
    configure_registry_path(registry_path)
    dataset_registry_module._registry = None
    return registry_path


_TEST_REGISTRY_PATH = _activate_employees_test_registry()


@pytest.fixture(autouse=True)
def _restore_test_registry_default():
    """
    Назначение:
        Возвращать тестовый default registry после каждого теста.

        Это делает suite устойчивым к тестам, которые временно переключают registry path
        на custom значение или сбрасывают его в `None`.
    """
    _activate_employees_test_registry()
    yield
    _activate_employees_test_registry()


@pytest.fixture()
def employees_registry_path():
    """
    Назначение:
        Переключить тестовый runtime на актуальный employees registry.

    Контракт:
        - использует изолированный `datasets/registry.yaml`;
        - сбрасывает dataset factory registry между тестами, чтобы не залипали результаты
          старого discovery-кеша;
        - не влияет на тесты, которые явно настраивают другой registry path.
    """
    try:
        _activate_employees_test_registry()
        yield _TEST_REGISTRY_PATH
    finally:
        _activate_employees_test_registry()
