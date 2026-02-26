"""
Интеграционные тесты для SqliteContainer.

Проверяют:
1. init_resources() создаёт все три engine Singleton без ошибок.
2. vault_engine доступен как Singleton (два обращения → один объект).
3. shutdown_resources() корректно завершает работу.

Примечание:
    VaultStartupGuard.ensure_ready() требует vault key material.
    Чтобы не усложнять тест настройкой vault-ключей, vault_ready
    переопределяется на заглушку через container.vault_ready.override().
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from dependency_injector import providers

from connector.config.models import AppConfig
from connector.delivery.cli.containers import SqliteContainer
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.sqlite.engine import SqliteEngine


def _noop_vault_resource(engine: SqliteEngine) -> Iterator[None]:
    """Заглушка для vault_ready: открыть engine без VaultStartupGuard."""
    yield
    engine.close()


def _make_container(tmp_path: Path) -> SqliteContainer:
    """
    Создать SqliteContainer с реальными DB-файлами и заглушкой для vault_ready.
    """
    cache_dir = str(tmp_path / "dbs")
    app_config = AppConfig()
    cache_specs = list(load_cache_dsl_runtime().cache_specs)

    container = SqliteContainer()
    container.app_config.override(app_config)
    container.cache_dir.override(cache_dir)
    container.cache_specs.override(cache_specs)
    # Заглушка vault startup resource (нет vault key material в тесте)
    container.vault_ready.override(
        providers.Resource(_noop_vault_resource, engine=container.vault_engine)
    )
    return container


def test_container_init_resources_creates_all_engines(tmp_path: Path):
    """
    container.init_resources() не бросает и создаёт все три SqliteEngine.
    """
    container = _make_container(tmp_path)
    try:
        container.init_resources()
        assert isinstance(container.cache_engine(), SqliteEngine)
        assert isinstance(container.vault_engine(), SqliteEngine)
        assert isinstance(container.identity_engine(), SqliteEngine)
    finally:
        container.shutdown_resources()


def test_container_vault_engine_is_singleton(tmp_path: Path):
    """
    Два обращения к container.vault_engine() возвращают один и тот же объект.
    """
    container = _make_container(tmp_path)
    try:
        container.init_resources()
        engine_a = container.vault_engine()
        engine_b = container.vault_engine()
        assert engine_a is engine_b
    finally:
        container.shutdown_resources()


def test_container_shutdown_resources_completes(tmp_path: Path):
    """
    init_resources() + shutdown_resources() завершается без исключений.
    """
    container = _make_container(tmp_path)
    container.init_resources()
    container.shutdown_resources()
