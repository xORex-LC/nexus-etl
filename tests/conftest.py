from __future__ import annotations

import os
from pathlib import Path

import pytest

from connector.datasets import registry as dataset_registry_module
from connector.domain.dsl.loader import configure_registry_path


# NOTE:
# На CI/локальных тестах режим WAL в некоторых средах может инициализироваться
# очень медленно для каждого нового файла БД. Для тестового контура достаточно
# режима DELETE, он существенно быстрее на cold-start.
os.environ.setdefault("ANKEY_SQLITE__CACHE_JOURNAL_MODE", "DELETE")


def _activate_employees_test_registry() -> Path:
    """
    Назначение:
        Включить `datasets/employees.registry.yaml` как дефолтный registry для тестового рантайма.

    Почему это здесь:
        Часть legacy-тестов строит `build_catalog()/get_spec()/load_*_for_dataset()`
        на уровне импорта модуля, то есть раньше обычных function-fixtures.
        Поэтому тестовый registry нужно активировать уже при загрузке `conftest.py`.
    """
    registry_path = Path(__file__).resolve().parents[1] / "datasets" / "employees.registry.yaml"
    configure_registry_path(registry_path)
    dataset_registry_module._registry = None
    return registry_path


_TEST_REGISTRY_PATH = _activate_employees_test_registry()
os.environ.setdefault("ANKEY_DATASET__REGISTRY_PATH", str(_TEST_REGISTRY_PATH))


@pytest.fixture(autouse=True)
def _restore_test_registry_default():
    """
    Назначение:
        Возвращать тестовый default registry после каждого теста.

        Это делает suite устойчивым к тестам, которые временно переключают registry path
        на custom значение или сбрасывают его в `None`.
    """
    configure_registry_path(_TEST_REGISTRY_PATH)
    dataset_registry_module._registry = None
    yield
    configure_registry_path(_TEST_REGISTRY_PATH)
    dataset_registry_module._registry = None


@pytest.fixture()
def employees_registry_path():
    """
    Назначение:
        Переключить тестовый runtime на актуальный employees registry.

    Контракт:
        - использует tracked `datasets/employees.registry.yaml`;
        - сбрасывает dataset factory registry между тестами, чтобы не залипали
          результаты старого discovery-кеша;
        - не влияет на тесты, которые явно настраивают другой registry path.
    """
    try:
        configure_registry_path(_TEST_REGISTRY_PATH)
        dataset_registry_module._registry = None
        yield _TEST_REGISTRY_PATH
    finally:
        configure_registry_path(_TEST_REGISTRY_PATH)
        dataset_registry_module._registry = None
