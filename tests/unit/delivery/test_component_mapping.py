"""Юнит-тесты delivery-маппинга CLI-команда → ServiceComponent."""

from __future__ import annotations

import pytest

from connector.common.observability import ServiceComponent
from connector.delivery.cli.component_mapping import component_for_command

pytestmark = pytest.mark.unit


def test_component_for_command_covers_current_command_surface() -> None:
    assert component_for_command("mapping") is ServiceComponent.MAPPER
    assert component_for_command("normalize") is ServiceComponent.NORMALIZER
    assert component_for_command("enrich") is ServiceComponent.ENRICHER
    assert component_for_command("match") is ServiceComponent.MATCHER
    assert component_for_command("resolve") is ServiceComponent.RESOLVER
    assert component_for_command("import-plan") is ServiceComponent.PLANNER
    assert component_for_command("import_apply") is ServiceComponent.APPLIER
    assert component_for_command("cache-refresh") is ServiceComponent.CACHE
    assert component_for_command("vault-status") is ServiceComponent.VAULT
    assert component_for_command("check-api") is ServiceComponent.TOPOLOGY


def test_component_for_command_fails_fast_on_unknown_command() -> None:
    with pytest.raises(KeyError):
        component_for_command("totally-unknown")
